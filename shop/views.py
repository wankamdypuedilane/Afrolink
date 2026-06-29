# shop/views.py
import json
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.http import HttpResponse
from django.contrib import messages
from django.core.paginator import Paginator
from django.contrib.auth import login, logout
from .forms import SignupForm, EmailAuthenticationForm, PlatForm, AvisForm
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from .models import Plat, Category, Commande, OrderItem, Profile, Avis
from django.db.models import Avg
from .services import (
    sync_commande_payment_from_stripe,
    stripe_is_configured,
    create_stripe_checkout_session,
    calculate_tax_totals,
    get_tax_rate_percent,
    send_order_confirmation_email,
    verifier_siret,
)

try:
    import stripe
except ImportError:
    stripe = None

import logging


logger = logging.getLogger(__name__)


def render_checkout_error(request, error_message):
    return render(request, 'shop/checkout.html', {
        'error': error_message,
        'tax_rate_percent': get_tax_rate_percent(),
    })


def index(request):
    plats = Plat.objects.select_related('category').all()
    categories = Category.objects.all()

    item_name = request.GET.get('item-name', '').strip()
    selected_category = request.GET.get('category', '').strip()

    if item_name:
        plats = plats.filter(title__icontains=item_name)

    selected_category_id = None
    if selected_category.isdigit():
        selected_category_id = int(selected_category)
        plats = plats.filter(category_id=selected_category_id)

    paginator = Paginator(plats, 4)
    page = request.GET.get('page')
    plats = paginator.get_page(page)
    return render(request, 'shop/index.html', {
        'plats': plats,
        'categories': categories,
        'item_name': item_name,
        'selected_category_id': selected_category_id,
    })


def search_products(request):
    plats = Plat.objects.select_related('category').all()
    item_name = request.GET.get('item-name', '').strip()
    selected_category = request.GET.get('category', '').strip()

    if item_name:
        plats = plats.filter(title__icontains=item_name)

    if selected_category.isdigit():
        plats = plats.filter(category_id=int(selected_category))

    plats = plats.order_by('title')[:24]

    return JsonResponse({
        'products': [
            {
                'id': product.id,
                'title': product.title,
                'price': str(product.price),
                'image': product.display_image_url,
                'stock': product.stock,
            }
            for product in plats
        ]
    })


def detail(request, myid):
    plat = get_object_or_404(Plat, id=myid)
    avis = plat.avis.all()                          # tous les avis de ce plat (grâce au related_name)
    stats = avis.aggregate(moyenne=Avg('note'))     # calcule la moyenne des notes
    note_moyenne = stats['moyenne']                 # None s'il n'y a aucun avis
    return render(request, 'shop/detail.html', {
        'product': plat,
        'avis': avis,
        'note_moyenne': note_moyenne,
        'nombre_avis': avis.count(),
    })

@login_required(login_url='/connexion/')
def checkout(request):
    if request.method == "POST":
        # 1. Récupérer les infos client
        nom     = request.POST.get("nom", "").strip()
        email   = request.POST.get("email", "").strip()
        address = request.POST.get("address", "").strip()
        address2 = request.POST.get("address2", "").strip()
        ville   = request.POST.get("ville", "").strip()
        pays    = request.POST.get("pays", "").strip()
        zipcode = request.POST.get("zipcode", "").strip()

        # 2. Vérifier les champs obligatoires
        if not nom or not email or not address:
            return render_checkout_error(request, 'Veuillez remplir tous les champs obligatoires.')

        # 3. Récupérer les articles envoyés par le navigateur
        items_json = request.POST.get("items", "[]")

        try:
            items_data = json.loads(items_json)
            # items_data ressemble à :
            # [{"id": 1, "quantity": 2}, {"id": 3, "quantity": 1}]
        except (json.JSONDecodeError, TypeError):
            return render_checkout_error(request, 'Panier invalide, veuillez réessayer.')

        if not items_data:
            return render_checkout_error(request, 'Votre panier est vide.')

        requested_quantities = {}
        ordered_product_ids = []
        for item in items_data:
            try:
                product_id = int(item.get("id"))
                quantity = int(item.get("quantity", 1))
            except (ValueError, TypeError):
                continue

            if quantity < 1:
                continue

            if product_id not in requested_quantities:
                ordered_product_ids.append(product_id)
                requested_quantities[product_id] = 0
            requested_quantities[product_id] += quantity

        if not requested_quantities:
            return render_checkout_error(request, 'Aucun produit valide dans le panier.')

        with transaction.atomic():
            products = {
                product.id: product
                for product in Plat.objects.select_for_update().filter(id__in=ordered_product_ids)
            }

            total_calcule = 0
            items_verifies = []
            order_items_to_create = []

            for product_id in ordered_product_ids:
                product = products.get(product_id)
                if not product:
                    continue

                quantity = requested_quantities[product_id]
                if product.stock < quantity:
                    return render_checkout_error(
                        request,
                        f'Stock insuffisant pour "{product.title}" (disponible : {product.stock})'
                    )

                prix_reel = product.price
                sous_total = prix_reel * quantity
                total_calcule += sous_total

                items_verifies.append({
                    "id": product.id,
                    "title": product.title,
                    "price": str(prix_reel),
                    "quantity": quantity,
                    "subtotal": str(sous_total),
                })

                order_items_to_create.append(
                    OrderItem(
                        plat=product,
                        price=prix_reel,
                        quantity=quantity,
                    )
                )

            if not items_verifies:
                return render_checkout_error(request, 'Aucun produit valide dans le panier.')

            subtotal_ht = total_calcule
            tax_rate_percent, tax_amount, total_ttc = calculate_tax_totals(subtotal_ht)

            commande = Commande.objects.create(
                subtotal_ht=subtotal_ht,
                tax_amount=tax_amount,
                total=total_ttc,
                nom=nom,
                email=email,
                address=address,
                address2=address2,
                ville=ville,
                pays=pays,
                zipcode=zipcode,
                user=request.user if request.user.is_authenticated else None,
            )

            for order_item in order_items_to_create:
                order_item.commande = commande

            OrderItem.objects.bulk_create(order_items_to_create)

            session = create_stripe_checkout_session(
                request,
                commande,
                items_verifies,
                email,
                tax_amount=tax_amount,
                rate_percent=tax_rate_percent,
            )
            if session:
                commande.stripe_checkout_session_id = session.id
                commande.payment_status = 'processing'
                commande.save(update_fields=['stripe_checkout_session_id', 'payment_status'])

                return redirect(session.url, permanent=False)

        messages.success(request, f"Merci {nom}, votre commande a bien été enregistrée !")
        return redirect('confirmation_order', order_id=commande.id)

    return render(request, 'shop/checkout.html', {
        'tax_rate_percent': get_tax_rate_percent(),
    })


def confirmation(request, order_id=None):
    if order_id is None:
        commande = Commande.objects.order_by('-id').first()
    else:
        commande = get_object_or_404(Commande, id=order_id)

    if commande and commande.payment_status == 'processing':
        try:
            sync_commande_payment_from_stripe(commande)
        except Exception as exc:
            logger.warning("Stripe sync in confirmation failed for order %s: %s", commande.id, exc)

    if commande and commande.payment_status == 'paid' and not commande.confirmation_email_sent:
        try:
            send_order_confirmation_email(commande)
        except Exception as exc:
            logger.exception("Recovery confirmation email failed for order %s: %s", commande.id, exc)

    nom = commande.nom if commande else "Client"
    return render(request, 'shop/confirmation.html', {
        'nom': nom,
        'commande': commande,
        'payment_status': commande.payment_status if commande else 'pending',
        'clear_cart': bool(commande and commande.payment_status in ['paid', 'processing']),
    })


def payment_success(request):
    order_id = request.GET.get('order_id')
    session_id = request.GET.get('session_id', '')

    if not order_id:
        messages.error(request, "Commande introuvable après paiement.")
        return redirect('home')

    commande = get_object_or_404(Commande, id=order_id)

    if stripe_is_configured() and session_id:
        try:
            sync_commande_payment_from_stripe(commande, session_id=session_id)
        except Exception as exc:
            logger.exception("Stripe payment_success sync failed for order %s: %s", commande.id, exc)
            messages.warning(request, "Paiement en cours de vérification. Rechargez dans quelques secondes.")

    if commande.payment_status == 'paid' and not commande.confirmation_email_sent:
        try:
            send_order_confirmation_email(commande)
        except Exception as exc:
            logger.exception("Recovery confirmation email in payment_success failed for order %s: %s", commande.id, exc)

    return redirect('confirmation_order', order_id=commande.id)


def payment_cancel(request):
    order_id = request.GET.get('order_id')
    if order_id and str(order_id).isdigit():
        commande = Commande.objects.filter(id=order_id).first()
        if commande and commande.payment_status in ['pending', 'processing']:
            update_fields = ['payment_status']
            commande.payment_status = 'cancelled'
            if commande.stock_deducted:
                order_items = OrderItem.objects.filter(commande=commande).select_related('plat')
                for item in order_items:
                    if item.plat:
                        item.plat.stock += item.quantity
                        item.plat.save(update_fields=['stock'])
                commande.stock_deducted = False
                update_fields.append('stock_deducted')
            commande.save(update_fields=update_fields)

    messages.info(request, "Le paiement a été annulé. Vous pouvez réessayer.")
    return redirect('checkout')


@csrf_exempt
def stripe_webhook(request):
    if not stripe_is_configured() or not settings.STRIPE_WEBHOOK_SECRET:
        logger.error("Stripe webhook rejected: missing Stripe configuration or webhook secret.")
        return HttpResponse(status=400)

    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')

    try:
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except Exception as exc:
        logger.exception("Stripe webhook signature verification failed: %s", exc)
        return HttpResponse(status=400)

    if event['type'] == 'checkout.session.completed':
        try:
            session = event['data']['object']
            session_id = getattr(session, 'id', None)

            commande = Commande.objects.filter(stripe_checkout_session_id=session_id).first()
            if not commande:
                metadata = getattr(session, 'metadata', {}) or {}
                commande_id = metadata.get('commande_id') if hasattr(metadata, 'get') else None
                if commande_id and str(commande_id).isdigit():
                    commande = Commande.objects.filter(id=int(commande_id)).first()

            if commande:
                sync_commande_payment_from_stripe(commande, session_id=session_id)

                # Décrémenter le stock une seule fois, seulement après paiement confirmé.
                with transaction.atomic():
                    commande_locked = Commande.objects.select_for_update().filter(id=commande.id).first()
                    if commande_locked and commande_locked.payment_status == 'paid' and not commande_locked.stock_deducted:
                        order_items = list(OrderItem.objects.filter(commande=commande_locked).select_related('plat'))
                        for item in order_items:
                            if not item.plat:
                                continue
                            product = Plat.objects.select_for_update().filter(id=item.plat_id).first()
                            if not product:
                                continue
                            product.stock = max(0, product.stock - item.quantity)
                            product.save(update_fields=['stock'])

                        commande_locked.stock_deducted = True
                        commande_locked.save(update_fields=['stock_deducted'])
        except Exception as exc:
            logger.exception("Stripe checkout.session.completed processing failed: %s", exc)
            return HttpResponse(status=200)

    elif event['type'] == 'checkout.session.expired':
        session = event['data']['object']
        session_id = getattr(session, 'id', None)
        commande = Commande.objects.filter(stripe_checkout_session_id=session_id).first()
        if commande and commande.payment_status in ['pending', 'processing']:
            update_fields = ['payment_status']
            commande.payment_status = 'cancelled'
            if commande.stock_deducted:
                order_items = OrderItem.objects.filter(commande=commande).select_related('plat')
                for item in order_items:
                    if item.plat:
                        item.plat.stock += item.quantity
                        item.plat.save(update_fields=['stock'])
                commande.stock_deducted = False
                update_fields.append('stock_deducted')
            commande.save(update_fields=update_fields)

    return HttpResponse(status=200)


def inscription(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            role = form.cleaned_data['role']
            siret = form.cleaned_data.get('siret', '').strip()

            # Préparation des valeurs SIRET selon le rôle
            siret_a_enregistrer = ''
            siret_verifie = False

            if role == 'cuisinier' and siret:
                resultat = verifier_siret(siret)

                if resultat['raison'] == 'format':
                    # Format invalide = erreur de saisie évidente → on bloque
                    messages.error(request, "Le SIRET doit comporter 14 chiffres.")
                    return render(request, 'shop/inscription.html', {'form': form})

                # Format OK : on enregistre le SIRET, vérifié ou non
                siret_a_enregistrer = siret
                siret_verifie = resultat['valide']

                if resultat['valide']:
                    messages.success(request, f"SIRET vérifié : {resultat['nom']}")
                else:
                    messages.warning(request, "SIRET enregistré mais non vérifié (introuvable ou service indisponible). Vous pourrez le confirmer plus tard.")

            # Création du compte
            user = form.save()
            Profile.objects.create(
                user=user,
                role=role,
                siret=siret_a_enregistrer,
                siret_verifie=siret_verifie,
            )
            login(request, user)
            messages.success(request, f"Bienvenue {user.username}, votre compte a été créé !")
            return redirect('home')
    else:
        form = SignupForm()
    return render(request, 'shop/inscription.html', {'form': form})


def devenir_auto_entrepreneur(request):
    return render(request, 'shop/devenir_auto_entrepreneur.html')


def connexion(request):
    if request.method == 'POST':
        form = EmailAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"Bienvenue {user.username} !")
            return redirect('home')
    else:
        form = EmailAuthenticationForm(request)
    return render(request, 'shop/connexion.html', {'form': form})


def deconnexion(request):
    logout(request)
    messages.success(request, "Vous avez été déconnecté.")
    return redirect('home')


@login_required(login_url='/connexion/')
def profil(request):
    commandes = Commande.objects.filter(user=request.user).prefetch_related('order_items__plat').order_by('-date_commande')
    return render(request, 'shop/mes_commandes.html', {'commandes': commandes})

@login_required(login_url='/connexion/')
def espace_cuisinier(request):
    # Barrière 2 : cuisinier ?
    if request.user.profile.role != 'cuisinier':
        messages.error(request, "Cet espace est réservé aux cuisiniers.")
        return redirect('home')

    return render(request, 'shop/espace_cuisinier.html')

@login_required(login_url='/connexion/')
def ajouter_plat(request):
    # Barrière 2 : est-ce un cuisinier ?
    if request.user.profile.role != 'cuisinier':
        messages.error(request, "Seuls les cuisiniers peuvent ajouter un plat.")
        return redirect('home')

    if request.method == 'POST':
        form = PlatForm(request.POST, request.FILES)
        if form.is_valid():
            plat = form.save(commit=False)
            plat.cuisinier = request.user
            plat.save()
            messages.success(request, f"Le plat « {plat.title} » a été ajouté !")
            # On regarde quel bouton a été cliqué
            if request.POST.get('action') == 'continuer':
                return redirect('ajouter_plat')   # reste sur le formulaire
            else:
                return redirect('mes_plats')      # va voir ses plats
    else:
        form = PlatForm()

    return render(request, 'shop/ajouter_plat.html', {'form': form})

@login_required(login_url='/connexion/')
def mes_plats(request):
    # Barrière 2 : est-ce un cuisinier ?
    if request.user.profile.role != 'cuisinier':
        messages.error(request, "Seuls les cuisiniers ont un espace plats.")
        return redirect('home')

    # Filtrage : uniquement les plats de CE cuisinier
    plats = Plat.objects.filter(cuisinier=request.user)

    return render(request, 'shop/mes_plats.html', {'plats': plats})

@login_required(login_url='/connexion/')
def modifier_plat(request, myid):
    # Barrière 2 : cuisinier ?
    if request.user.profile.role != 'cuisinier':
        messages.error(request, "Seuls les cuisiniers peuvent modifier un plat.")
        return redirect('home')

    # Sécurité : récupère le plat SEULEMENT s'il appartient au cuisinier connecté
    plat = get_object_or_404(Plat, id=myid, cuisinier=request.user)

    if request.method == 'POST':
        form = PlatForm(request.POST, request.FILES, instance=plat)
        if form.is_valid():
            form.save()
            messages.success(request, f"Le plat « {plat.title} » a été modifié !")
            return redirect('mes_plats')
    else:
        form = PlatForm(instance=plat)

    return render(request, 'shop/modifier_plat.html', {'form': form, 'plat': plat})

@login_required(login_url='/connexion/')
def supprimer_plat(request, myid):
    # Barrière 2 : cuisinier ?
    if request.user.profile.role != 'cuisinier':
        messages.error(request, "Seuls les cuisiniers peuvent supprimer un plat.")
        return redirect('home')

    # Même sécurité que modifier : le plat doit appartenir au cuisinier connecté
    plat = get_object_or_404(Plat, id=myid, cuisinier=request.user)

    if request.method == 'POST':
        titre = plat.title
        plat.delete()
        messages.success(request, f"Le plat « {titre} » a été supprimé.")
        return redirect('mes_plats')

    # En GET : on affiche une page de confirmation
    return render(request, 'shop/supprimer_plat.html', {'plat': plat})

@login_required(login_url='/connexion/')
def commandes_recues(request):
    # Barrière : cuisinier ?
    if request.user.profile.role != 'cuisinier':
        messages.error(request, "Cet espace est réservé aux cuisiniers.")
        return redirect('home')

    # Les lignes de commande : ses plats + commandes payées
    lignes = OrderItem.objects.filter(
        plat__cuisinier=request.user,
        commande__payment_status='paid'
    ).select_related('plat', 'commande').order_by('-commande__date_commande')

    return render(request, 'shop/commandes_recues.html', {'lignes': lignes})

@login_required(login_url='/connexion/')
def ajouter_avis(request, myid):
    plat = get_object_or_404(Plat, id=myid)

    # Règle 1 : le cuisinier ne peut pas noter son propre plat
    if plat.cuisinier == request.user:
        messages.error(request, "Vous ne pouvez pas noter votre propre plat.")
        return redirect('detail', myid=plat.id)

    # Règle 2 : un seul avis par plat et par utilisateur
    if Avis.objects.filter(plat=plat, user=request.user).exists():
        messages.error(request, "Vous avez déjà laissé un avis sur ce plat.")
        return redirect('detail', myid=plat.id)

    if request.method == 'POST':
        form = AvisForm(request.POST)
        if form.is_valid():
            avis = form.save(commit=False)
            avis.plat = plat
            avis.user = request.user
            avis.save()
            messages.success(request, "Merci pour votre avis !")
            return redirect('detail', myid=plat.id)
    else:
        form = AvisForm()

    return render(request, 'shop/ajouter_avis.html', {'form': form, 'plat': plat})