select cron.alter_job(
  (select jobid from cron.job where jobname = 'orbita-daily-notifications'),
  schedule := '*/15 * * * *'
);
