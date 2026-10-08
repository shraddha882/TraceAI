from django.contrib.auth.forms import AuthenticationForm, UserCreationForm


class WorkspaceAuthenticationForm(AuthenticationForm):
    """Allow active registered users; Django rejects inactive accounts."""


class SignUpForm(UserCreationForm):
    """Create ordinary accounts using Django's password validation and hashing."""
