"""
Réinitialisation directe d'un mot de passe (accès terminal local).

    python manage.py reset_password <username> [--password NOUVEAU]

Sans --password, un mot de passe aléatoire est généré et affiché. Utile pour
le support sur site ou le développeur ; ne nécessite ni ancien mot de passe ni
question secrète.
"""
import secrets
import string

from django.core.management.base import BaseCommand, CommandError

from users.models import User


class Command(BaseCommand):
    help = "Réinitialise le mot de passe d'un utilisateur"

    def add_arguments(self, parser):
        parser.add_argument('username')
        parser.add_argument('--password', default=None,
                            help='Nouveau mot de passe (généré aléatoirement si omis)')

    def handle(self, *args, **options):
        try:
            user = User.objects.get(username__iexact=options['username'])
        except User.DoesNotExist:
            raise CommandError(f"Utilisateur '{options['username']}' introuvable")

        password = options['password']
        if not password:
            alphabet = string.ascii_letters + string.digits
            password = ''.join(secrets.choice(alphabet) for _ in range(12))

        if len(password) < 8:
            raise CommandError('Le mot de passe doit contenir au moins 8 caractères')

        user.set_password(password)
        user.save(update_fields=['password'])

        self.stdout.write(self.style.SUCCESS(
            f"Mot de passe de '{user.username}' réinitialisé.\n"
            f"Nouveau mot de passe : {password}"))
