from django import forms
from .models import Plat, Category, Avis, Profile
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm


User = get_user_model()


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )


class SignupForm(UserCreationForm):
    email = forms.EmailField(required=True, label="Email")

    ROLE_CHOICES = [
        ('client', 'Je veux commander des plats'),
        ('cuisinier', 'Je veux vendre mes plats'),
    ]
    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        widget=forms.RadioSelect,
        initial='client',
        label="Vous êtes ?",
    )

    siret = forms.CharField(
        required=False,
        label="Numéro SIRET (pour les cuisiniers)",
        max_length=14,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '14 chiffres',
        }),
    )

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Cet email est deja utilise.")
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user

class PlatForm(forms.ModelForm):
    class Meta:
        model = Plat
        fields = ['title', 'price', 'description', 'category', 'image_file', 'stock']
        labels = {
            'title':       'Nom du plat',
            'price':       'Prix (€)',
            'description': 'Description',
            'category':    'Catégorie',
            'image_file':  'Photo du plat',
            'stock':       'Nombre de portions disponibles',
        }
        widgets = {
            'title':       forms.TextInput(attrs={'class': 'form-control'}),
            'price':       forms.NumberInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'category':    forms.Select(attrs={'class': 'form-select'}),
            'image_file':  forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'stock':       forms.NumberInput(attrs={'class': 'form-control'}),
        }

class AvisForm(forms.ModelForm):
    class Meta:
        model = Avis
        fields = ['note', 'commentaire']
        labels = {
            'note': 'Votre note',
            'commentaire': 'Votre commentaire (optionnel)',
        }
        widgets = {
            'note': forms.Select(attrs={'class': 'form-select'}),
            'commentaire': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = ['ville', 'telephone']
        labels = {
            'ville': 'Ville',
            'telephone': 'Téléphone',
        }
        widgets = {
            'ville': forms.TextInput(attrs={'class': 'form-control'}),
            'telephone': forms.TextInput(attrs={'class': 'form-control'}),
        }