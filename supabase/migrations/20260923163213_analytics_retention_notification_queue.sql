create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

alter table public.notification_subscriptions
  add column if not exists next_send_at timestamptz;

update public.notification_subscriptions
set next_send_at = (
  case
    when (now() at time zone timezone)::time < make_time(preferred_hour, 0, 0)
      then (now() at time zone timezone)::date + make_time(preferred_hour, 0, 0)
    else (now() at time zone timezone)::date + 1 + make_time(preferred_hour, 0, 0)
  end
) at time zone timezone
where next_send_at is null;

alter table public.notification_subscriptions
  alter column next_send_at set not null;

create index if not exists notification_subscriptions_due_idx
  on public.notification_subscriptions (next_send_at)
  where enabled;

create table if not exists public.notification_deliveries (
  id bigint generated always as identity primary key,
  user_key text not null references public.notification_subscriptions(user_key) on delete cascade,
  local_date date not null,
  scheduled_for timestamptz not null,
  status text not null default 'pending'
    check (status in ('pending', 'processing', 'retry', 'sent', 'failed', 'cancelled')),
  attempts smallint not null default 0 check (attempts between 0 and 10),
  next_attempt_at timestamptz not null default now(),
  locked_until timestamptz,
  last_error text,
  sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_key, local_date)
);

comment on table public.notification_deliveries is
  'Durable delivery queue for daily Telegram forecasts. Payload is derived from the current subscription at claim time.';

create index if not exists notification_deliveries_ready_idx
  on public.notification_deliveries (next_attempt_at, id)
  where status in ('pending', 'retry');

alter table public.notification_deliveries enable row level security;
revoke all on table public.notification_deliveries from anon, authenticated;
revoke all on sequence public.notification_deliveries_id_seq from anon, authenticated;
grant select, insert, update, delete on table public.notification_deliveries to service_role;
grant usage, select on sequence public.notification_deliveries_id_seq to service_role;

create or replace function public.enqueue_due_notification_deliveries(p_limit integer default 5000)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  queued_count integer;
begin
  with due as materialized (
    select
      s.user_key,
      (s.next_send_at at time zone s.timezone)::date as local_date,
      s.next_send_at as scheduled_for
    from public.notification_subscriptions s
    where s.enabled
      and s.next_send_at <= now()
    order by s.next_send_at
    limit least(greatest(p_limit, 1), 5000)
    for update skip locked
  ), inserted as (
    insert into public.notification_deliveries (user_key, local_date, scheduled_for)
    select d.user_key, d.local_date, d.scheduled_for
    from due d
    on conflict (user_key, local_date) do nothing
    returning 1
  ), advanced as (
    update public.notification_subscriptions s
    set
      next_send_at = (
        (now() at time zone s.timezone)::date
        + 1
        + make_time(s.preferred_hour, 0, 0)
      ) at time zone s.timezone,
      updated_at = now()
    from due d
    where s.user_key = d.user_key
    returning 1
  )
  select count(*) into queued_count from inserted;

  return queued_count;
end;
$$;

revoke all on function public.enqueue_due_notification_deliveries(integer) from public, anon, authenticated;
grant execute on function public.enqueue_due_notification_deliveries(integer) to service_role;

create or replace function public.claim_notification_deliveries(p_limit integer default 100)
returns table (
  delivery_id bigint,
  user_key text,
  attempts smallint,
  local_date date,
  telegram_chat_id bigint,
  timezone text,
  birth_date date,
  birth_time time without time zone,
  latitude double precision,
  longitude double precision
)
language plpgsql
security definer
set search_path = ''
as $$
begin
  update public.notification_deliveries d
  set
    status = case when d.attempts >= 5 then 'failed' else 'retry' end,
    next_attempt_at = case when d.attempts >= 5 then d.next_attempt_at else now() end,
    locked_until = null,
    last_error = coalesce(d.last_error, 'Worker lease expired'),
    updated_at = now()
  where d.status = 'processing'
    and d.locked_until < now();

  update public.notification_deliveries d
  set status = 'cancelled', locked_until = null, updated_at = now()
  from public.notification_subscriptions s
  where d.user_key = s.user_key
    and not s.enabled
    and d.status in ('pending', 'retry');

  return query
  with candidates as (
    select d.id
    from public.notification_deliveries d
    join public.notification_subscriptions s on s.user_key = d.user_key
    where s.enabled
      and d.status in ('pending', 'retry')
      and d.attempts < 5
      and d.next_attempt_at <= now()
    order by d.next_attempt_at, d.id
    limit least(greatest(p_limit, 1), 100)
    for update of d skip locked
  ), claimed as (
    update public.notification_deliveries d
    set
      status = 'processing',
      attempts = d.attempts + 1,
      locked_until = now() + interval '5 minutes',
      updated_at = now()
    from candidates c
    where d.id = c.id
    returning d.id, d.user_key, d.attempts, d.local_date
  )
  select
    c.id,
    c.user_key,
    c.attempts,
    c.local_date,
    s.telegram_chat_id,
    s.timezone,
    s.birth_date,
    s.birth_time,
    s.latitude,
    s.longitude
  from claimed c
  join public.notification_subscriptions s on s.user_key = c.user_key;
end;
$$;

revoke all on function public.claim_notification_deliveries(integer) from public, anon, authenticated;
grant execute on function public.claim_notification_deliveries(integer) to service_role;

create or replace function private.cleanup_orbita_data()
returns void
language plpgsql
set search_path = ''
as $$
begin
  delete from public.analytics_events
  where occurred_at < now() - interval '90 days';

  delete from public.notification_deliveries
  where status in ('sent', 'failed', 'cancelled')
    and updated_at < now() - interval '30 days';

  delete from cron.job_run_details
  where end_time < now() - interval '7 days';
end;
$$;

revoke all on function private.cleanup_orbita_data() from public, anon, authenticated;

do $$
declare
  existing_job bigint;
begin
  select jobid into existing_job
  from cron.job
  where jobname = 'orbita-data-retention'
  limit 1;

  if existing_job is not null then
    perform cron.unschedule(existing_job);
  end if;
end
$$;

select cron.schedule(
  'orbita-data-retention',
  '17 3 * * *',
  $job$select private.cleanup_orbita_data();$job$
);
