create table public.notification_test_admins (
  user_key text primary key,
  last_test_sent_at timestamptz,
  created_at timestamptz not null default now(),
  constraint notification_test_admins_user_key_check
    check (user_key ~ '^[0-9a-f]{64}$')
);

comment on table public.notification_test_admins is
  'Server-only allowlist for immediate test forecast delivery.';

alter table public.notification_test_admins enable row level security;
revoke all on table public.notification_test_admins from anon, authenticated;
grant select, insert, update, delete on table public.notification_test_admins to service_role;
