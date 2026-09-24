alter table public.analytics_events
  drop constraint if exists analytics_events_name_allowed;

alter table public.analytics_events
  add constraint analytics_events_name_allowed check (event_name = any (array[
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
    'daily_notification_opened',
    'forecast_share_clicked',
    'forecast_shared',
    'referral_opened'
  ]));
