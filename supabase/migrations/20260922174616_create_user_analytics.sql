create table if not exists public.analytics_users (
    user_key text primary key,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    last_platform text,
    language_code text,
    is_premium boolean,
    first_start_param text,
    last_start_param text,
    constraint analytics_users_key_format check (user_key ~ '^[0-9a-f]{64}$')
);

create table if not exists public.analytics_events (
    id bigint generated always as identity primary key,
    event_id uuid not null unique,
    user_key text not null references public.analytics_users(user_key) on delete cascade,
    event_name text not null,
    session_id uuid not null,
    occurred_at timestamptz not null default now(),
    client_occurred_at timestamptz,
    platform text,
    app_version text,
    metadata jsonb not null default '{}'::jsonb,
    constraint analytics_events_name_allowed check (event_name in (
        'app_open',
        'view_opened',
        'profile_completed',
        'daily_forecast_viewed',
        'forecast_details_opened',
        'natal_chart_viewed',
        'partner_profile_saved',
        'partner_chart_viewed',
        'compatibility_viewed',
        'matrix_viewed',
        'sphere_viewed',
        'dream_saved',
        'dream_edited',
        'dream_deleted',
        'dictionary_searched',
        'daily_notification_enabled',
        'daily_notification_disabled',
        'daily_notification_opened'
    )),
    constraint analytics_events_metadata_object check (jsonb_typeof(metadata) = 'object'),
    constraint analytics_events_metadata_size check (octet_length(metadata::text) <= 2048)
);

create index if not exists analytics_events_occurred_at_idx
    on public.analytics_events (occurred_at desc);

create index if not exists analytics_events_user_time_idx
    on public.analytics_events (user_key, occurred_at desc);

create index if not exists analytics_events_name_time_idx
    on public.analytics_events (event_name, occurred_at desc);

alter table public.analytics_users enable row level security;
alter table public.analytics_events enable row level security;

revoke all on table public.analytics_users from anon, authenticated;
revoke all on table public.analytics_events from anon, authenticated;
revoke all on sequence public.analytics_events_id_seq from anon, authenticated;

grant select, insert, update on table public.analytics_users to service_role;
grant select, insert on table public.analytics_events to service_role;
grant usage, select on sequence public.analytics_events_id_seq to service_role;

create or replace view public.analytics_daily_metrics
with (security_invoker = true)
as
with bounds as (
    select coalesce(min((first_seen_at at time zone 'UTC')::date), (now() at time zone 'UTC')::date) as first_day,
           (now() at time zone 'UTC')::date as today
    from public.analytics_users
), days as (
    select generate_series(first_day, today, interval '1 day')::date as metric_date
    from bounds
)
select
    days.metric_date,
    (select count(distinct user_key)
       from public.analytics_events
      where occurred_at >= days.metric_date::timestamptz
        and occurred_at < (days.metric_date + 1)::timestamptz) as dau,
    (select count(distinct user_key)
       from public.analytics_events
      where occurred_at >= (days.metric_date - 6)::timestamptz
        and occurred_at < (days.metric_date + 1)::timestamptz) as wau,
    (select count(distinct user_key)
       from public.analytics_events
      where occurred_at >= (days.metric_date - 29)::timestamptz
        and occurred_at < (days.metric_date + 1)::timestamptz) as mau,
    (select count(*)
       from public.analytics_users
      where first_seen_at >= days.metric_date::timestamptz
        and first_seen_at < (days.metric_date + 1)::timestamptz) as new_users,
    (select count(distinct session_id)
       from public.analytics_events
      where occurred_at >= days.metric_date::timestamptz
        and occurred_at < (days.metric_date + 1)::timestamptz) as sessions,
    (select count(*)
       from public.analytics_events
      where event_name = 'app_open'
        and occurred_at >= days.metric_date::timestamptz
        and occurred_at < (days.metric_date + 1)::timestamptz) as app_opens
from days
order by days.metric_date desc;

revoke all on table public.analytics_daily_metrics from anon, authenticated;
grant select on table public.analytics_daily_metrics to service_role;

comment on table public.analytics_users is
    'Pseudonymous Telegram Mini App users. Contains no birth profile or dream content.';

comment on table public.analytics_events is
    'Allowlisted product analytics events. Sensitive user-generated content is never stored here.';
