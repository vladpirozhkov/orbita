create extension if not exists pg_cron with schema pg_catalog;
create extension if not exists pg_net with schema extensions;

create table public.notification_subscriptions (
  user_key text primary key check (user_key ~ '^[0-9a-f]{64}$'),
  telegram_chat_id bigint not null unique,
  enabled boolean not null default true,
  timezone text not null,
  birth_date date not null,
  birth_time time without time zone not null,
  latitude double precision not null check (latitude between -90 and 90),
  longitude double precision not null check (longitude between -180 and 180),
  preferred_hour smallint not null default 9 check (preferred_hour between 0 and 23),
  last_sent_local_date date,
  last_sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table public.notification_subscriptions is
  'Opt-in Telegram forecast delivery. Birth data is stored only while the subscription exists.';

create index notification_subscriptions_enabled_idx
  on public.notification_subscriptions (enabled, preferred_hour)
  where enabled;

alter table public.notification_subscriptions enable row level security;
revoke all on table public.notification_subscriptions from anon, authenticated;
grant select, insert, update, delete on table public.notification_subscriptions to service_role;

create table public.notification_dispatch_config (
  key text primary key,
  value_hash text not null check (value_hash ~ '^[0-9a-f]{64}$')
);

alter table public.notification_dispatch_config enable row level security;
revoke all on table public.notification_dispatch_config from anon, authenticated;
grant select on table public.notification_dispatch_config to service_role;

do $$
declare
  secret_value text;
begin
  if not exists (
    select 1 from vault.secrets where name = 'orbita_notification_cron_secret'
  ) then
    secret_value := encode(extensions.gen_random_bytes(32), 'hex');
    perform vault.create_secret(
      secret_value,
      'orbita_notification_cron_secret',
      'Authenticates the hourly Orbita notification dispatcher'
    );
  else
    select decrypted_secret into secret_value
    from vault.decrypted_secrets
    where name = 'orbita_notification_cron_secret'
    limit 1;
  end if;

  insert into public.notification_dispatch_config (key, value_hash)
  values (
    'cron_secret_sha256',
    encode(extensions.digest(secret_value, 'sha256'), 'hex')
  )
  on conflict (key) do update set value_hash = excluded.value_hash;
end
$$;

select cron.schedule(
  'orbita-daily-notifications',
  '5 * * * *',
  $job$
    select net.http_post(
      url := 'https://orbita-api-25ja.onrender.com/v1/notifications/run',
      headers := jsonb_build_object(
        'Content-Type', 'application/json',
        'X-Orbita-Cron-Token', (
          select decrypted_secret
          from vault.decrypted_secrets
          where name = 'orbita_notification_cron_secret'
          limit 1
        )
      ),
      body := jsonb_build_object('scheduled_at', now())
    );
  $job$
);
