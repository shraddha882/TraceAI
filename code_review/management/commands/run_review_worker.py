import time
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, close_old_connections
from code_review.jobs import run_next_job
from incidents.jobs import run_next_rca_job


class Command(BaseCommand):
    help = 'Process queued PR reviews and incident RCA reports alongside the web server.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Process at most one job of each type and exit.')

    def handle(self, *args, **options):
        if connection.vendor != 'postgresql':
            raise CommandError('The review worker requires PostgreSQL for safe job locking.')
        self.stdout.write('Review worker started. Ctrl+C to stop.')
        try:
            while True:
                close_old_connections()
                worked = run_next_job()
                rca_worked = run_next_rca_job()
                if options['once']:
                    return
                if not worked and not rca_worked:
                    time.sleep(2)
        except KeyboardInterrupt:
            self.stdout.write('Worker stopped.')
