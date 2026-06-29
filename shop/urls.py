from django.urls import path
from django.contrib.auth import views as auth_views
from shop.views import (
    index,
    detail,
    checkout,
    confirmation,
    payment_success,
    payment_cancel,
    stripe_webhook,
    inscription,
    devenir_auto_entrepreneur,
    connexion,
    deconnexion,
    profil,
    mon_compte,
    devenir_cuisinier,
    mettre_a_jour_siret,
    ajouter_plat,
    mes_plats,
    modifier_plat,
    supprimer_plat,
    espace_cuisinier,
    commandes_recues,
    ajouter_avis,
    search_products,
)

urlpatterns = [
    path('api/produits/', search_products, name='search_products'),
    path('webhooks/stripe/', stripe_webhook, name='stripe_webhook'),
    path('', index, name='home'),
    path('<int:myid>', detail, name='detail'),
    path('checkout', checkout, name="checkout"),
    path('confirmation/<int:order_id>/', confirmation, name="confirmation_order"),
    path('confirmation', confirmation, name="confirmation"),
    path('paiement/succes/', payment_success, name='payment_success'),
    path('paiement/annule/', payment_cancel, name='payment_cancel'),
    path('inscription/', inscription, name='inscription'),
    path('devenir-auto-entrepreneur/', devenir_auto_entrepreneur, name='devenir_auto_entrepreneur'),
    path('connexion/', connexion, name='connexion'),
    path(
        'mot-de-passe-oublie/',
        auth_views.PasswordResetView.as_view(
            template_name='shop/password_reset_form.html',
            email_template_name='registration/password_reset_email.html',
            subject_template_name='registration/password_reset_subject.txt',
        ),
        name='password_reset'
    ),
    path(
        'mot-de-passe-oublie/envoye/',
        auth_views.PasswordResetDoneView.as_view(template_name='shop/password_reset_done.html'),
        name='password_reset_done'
    ),
    path(
        'reinitialisation/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(template_name='shop/password_reset_confirm.html'),
        name='password_reset_confirm'
    ),
    path(
        'reinitialisation/terminee/',
        auth_views.PasswordResetCompleteView.as_view(template_name='shop/password_reset_complete.html'),
        name='password_reset_complete'
    ),
    path('deconnexion/', deconnexion, name='deconnexion'),
    path('profil/', profil, name='profil'),
    path('mon-compte/', mon_compte, name='mon_compte'),
    path('devenir-cuisinier/', devenir_cuisinier, name='devenir_cuisinier'),
    path('mettre-a-jour-siret/', mettre_a_jour_siret, name='mettre_a_jour_siret'),
    path('ajouter-plat/', ajouter_plat, name='ajouter_plat'),
    path('mes-plats/', mes_plats, name='mes_plats'),
    path('modifier-plat/<int:myid>/', modifier_plat, name='modifier_plat'),
    path('supprimer-plat/<int:myid>/', supprimer_plat, name='supprimer_plat'),
    path('espace-cuisinier/', espace_cuisinier, name='espace_cuisinier'),
    path('commandes-recues/', commandes_recues, name='commandes_recues'),
    path('plat/<int:myid>/avis/', ajouter_avis, name='ajouter_avis'),
]
