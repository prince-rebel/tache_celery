from celery import current_task
from django.http import JsonResponse,HttpResponseRedirect,HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import json
from django.shortcuts import render,redirect
from django.conf import settings
import hmac
import hashlib
import logging
from .models import CompteZoom, ReunionZoom,Configuration
from .tache_celery import  marquer_compte_comme_inactif,celery_bulk_Remove_toExceptionAccounts,celery_bulk_make_permanent, celery_bulk_make_dynamic,start_meeting_task,revocation_licence,LicenceDetail,ajuster_statut_is_static,attribuer_licence_zoomCelery,retirer_licence_zoomCelery,UserUpdateFromZoomUsPlateforme,celery_bulk_add_toExceptionAccounts
from .tache_celery import sync_zoom_meetings
from django.db.models import Count,Q
from django.contrib import messages
from django.urls import reverse
from django.contrib.auth.decorators import login_required
ms_identity_web = settings.MS_IDENTITY_WEB
from django.views.decorators.http import require_http_methods
from datetime import datetime,timedelta
import xlwt 
from django.utils.timezone import now
from django.core import serializers
from account.decorators import  azure_ad_required

logger = logging.getLogger('django')

 
@csrf_exempt
def gestion_webhook_reunion(request):
   
    if request.method == 'POST':
        print(f"le message recu pour une reunion {request.body}")
        data =json.loads(request.body)
        event_type = data.get('event')
        if event_type == 'endpoint.url_validation':
            plaintoken =data.get('payload').get('plainToken')
            hash_for_validate = hmac.new(settings.ZOOM_SECRET_TOKEN.encode('utf-8'), plaintoken.encode('utf-8'), hashlib.sha256).hexdigest()
            response_data = {"plainToken": plaintoken,
            "encryptedToken": hash_for_validate}
            return JsonResponse(response_data, status=200)
        
        elif event_type in ['meeting.started', 'meeting.created']:
            host_id = data['payload']['object']['host_id']
            start_meeting_task.delay(host_id,data)
            logger.info(f"Meeting {event_type} with host user {host_id}")
            
        elif event_type == 'meeting.ended':
            id_reunion = data.get('payload').get('object').get('id')
            reunion = ReunionZoom.objects.filter(identifiant=id_reunion).first()
            
            if reunion:
                reunion.heure_fin = timezone.now()
                reunion.save()
                if not reunion.hote.is_static:
                    config = Configuration.objects.first()
                    revocation_licence.delay(reunion.hote.zoom_id,config.license_delay)

        elif event_type =='user.updated':
             UserUpdateFromZoomUsPlateforme.delay(data)
             
        # elif event_type =='meeting.created':
        #     host_id = data['payload']['object']['host_id']
        #     logger.info(f"Meeting create with host user {host_id}")            
        else:
            logger.info(f"Un meeting envoi des notifications avec les data {event_type}")
        
            
    return JsonResponse({'message': 'Méthode de requête non valide.'}, status=400)

def login(request):
    return render (request,'login.html')

@ms_identity_web.login_required
def index(request):
    comptes_zoom = CompteZoom.objects.all()
    return render (request,'liste_comptes.html',{'comptes_zoom':comptes_zoom})

@ms_identity_web.login_required
def liste_comptes(request):
    comptes_zoom = CompteZoom.objects.all()
    return render (request,'liste_comptes.html',{'comptes_zoom':comptes_zoom})

@ms_identity_web.login_required
def proteger_le_compte(request,id):
    date = timezone.now()
    compte =CompteZoom.objects.get(pk=id)
    compte.is_static =True
    compte.date_static_true =date,
    compte.save()
    return redirect('liste_comptes')
# def vider_compte_zoom():
#     # Supprimer tous les enregistrements de la table CompteZoom
#     CompteZoom.objects.all().delete()
#     print("Tous les enregistrements de la table CompteZoom ont été supprimés.")

@ms_identity_web.login_required
def statistiques(request):
    # Appel de la tâche asynchrone pour récupérer les détails de la licence
    result = LicenceDetail.delay()
    licencedetail = result.get()
    licenseTotal = licencedetail['hosts']
    licenceUtilisé = licencedetail['usage']
    licenceLibre = licenseTotal - licenceUtilisé

    # Calcul des statistiques globales
    total_comptes = CompteZoom.objects.count()
    reunions_en_cours = ReunionZoom.objects.filter(heure_fin__isnull=True).count()
    reunions_terminees = ReunionZoom.objects.filter(heure_fin__isnull=False).count()
    static = CompteZoom.objects.filter(is_static=True).count()
    dynamic = CompteZoom.objects.filter(is_static=False).count()
    compte_plus_de_reunions = (
        CompteZoom.objects.annotate(num_reunions=Count('reunionzoom'))
        .order_by('-num_reunions')
        .first()
    )
    licenceStatut = ['Licence Total', 'Libre', 'Utilisée']
    licenceNumber = [licenseTotal, licenceLibre, licenceUtilisé]
    reunionList = ['Réunion En cours', 'Réunion Terminée']
    ReunionNumber = [reunions_en_cours, reunions_terminees]
    dernieres_reunions = ReunionZoom.objects.order_by('-heure_debut')[:50]

    # Contexte pour le rendu du template
    context = {
        'total_comptes': total_comptes,
        'licences_disponibles': licenceLibre,
        'reunions_en_cours': reunions_en_cours,
        'reunions_terminees': reunions_terminees,
        'compte_plus_de_reunions': compte_plus_de_reunions,
        'compte_static': static,
        'compte_dynamic': dynamic,
        'total_licence': licenseTotal,
        'reunionList': reunionList,
        'ReunionNumber': ReunionNumber,
        'licenceStatut': licenceStatut,
        'licenceNumber': licenceNumber,
        'dernieres_reunions': dernieres_reunions,
    }

    # Gestion des requêtes AJAX pour le filtrage
    if request.method == 'GET' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        date_start = request.GET.get('date_start')  # 'YYYY-MM-DD'
        heure_start = request.GET.get('heure_start')  # 'HH:MM'
        date_end = request.GET.get('date_end')  # 'YYYY-MM-DD'
        heure_end = request.GET.get('heure_end')  # 'HH:MM'

        filters = {}

        # Gestion des filtres de début
        if date_start and heure_start:
            start_datetime_str = f"{date_start} {heure_start}"
            start_datetime = parse_datetime(start_datetime_str)
            filters['heure_debut__gte'] = start_datetime

        # Gestion des filtres de fin
        if date_end and heure_end:
            end_datetime_str = f"{date_end} {heure_end}"
            end_datetime = parse_datetime(end_datetime_str)
            filters['heure_debut__lte'] = end_datetime
        elif date_end:  # Si seule la date de fin est donnée
            end_datetime = datetime.strptime(date_end, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
            filters['heure_debut__lte'] = end_datetime
        if heure_end:
            filters['heure_fin__lte'] = parse_datetime(f"{date_end} {heure_end}") if date_end else parse_datetime(f"1970-01-01 {heure_end}")

        # Application des filtres sur les réunions
        reunions = ReunionZoom.objects.filter(**filters)

        # Construction des données à renvoyer
        reunions_data = []
        for reunion in reunions:
            reunions_data.append({
                'sujet': reunion.sujet,
                'identifiant': reunion.identifiant,
                'hote': reunion.hote.nom,  # Assumons que hote est un objet CompteZoom
                'heure_debut': reunion.heure_debut.strftime('%Y-%m-%d %H:%M'),
                'heure_fin': reunion.heure_fin.strftime('%Y-%m-%d %H:%M') if reunion.heure_fin else 'N/A',
            })

        # Retour des données JSON
        return JsonResponse({
            'reunions': reunions_data,
            'count': len(reunions_data),
        })

    # Rendu du template pour les requêtes non-AJAX
    return render(request, 'dashboard.html', context)

@ms_identity_web.login_required
def update_license_delay(request):
    message = ""
    if request.method == 'POST':
        # Récupération des données du formulaire
        license_delay = int(request.POST.get('license_delay', 0))
        time_before_change_user_status_licence = int(request.POST.get('time_before_change_user_status_licence', 0))
        numbre_of_meeting_must_do = int(request.POST.get('numbre_of_meeting_must_do', 0))
        number_must_do_inactif = int(request.POST.get('number_must_do_inactif', 0))
        day_before_inactif = int(request.POST.get('day_before_inactif', 0))

        config_instance, created = Configuration.objects.get_or_create(pk=1)
        config_instance.license_delay = license_delay
        config_instance.time_before_change_user_status_licence = time_before_change_user_status_licence
        config_instance.numbre_of_meeting_must_do = numbre_of_meeting_must_do
        config_instance.number_must_do_inactif = number_must_do_inactif
        config_instance.day_before_inactif = day_before_inactif

        try:
            config_instance.save()
            message = "Les paramètres ont été mis à jour avec succès."
        except Exception as e:
            message = "Une erreur s'est produite lors de la mise à jour des paramètres : {}".format(str(e))

    config_instance = Configuration.objects.first()
    return render(request, 'configuration.html', {"config_instance": config_instance, "message": message})

def rendre_permanent(request,id):
    compte = CompteZoom.objects.get(pk=id)
    compte.is_static = True
    compte.label_licence="Licence"
    compte.date_static_true = timezone.now()
    compte.is_inactif=False
    result =attribuer_licence_zoomCelery(compte.email)
    if result ==204:
        compte.save()
        return redirect('liste_comptes')
    else:
        messages.error(request, f"Le changement n'a pu être effectué. Erreur: {result}")
    return redirect('liste_comptes')

def rendre_dynamique(request,id):
    compte = CompteZoom.objects.get(pk=id)
    compte.is_static = False
    compte.date_static_false =timezone.now()
    compte.label_licence="Basique"
    compte.is_inactif=False
    result=retirer_licence_zoomCelery(compte.email)
    if result == 204:
        compte.save()
        return redirect("liste_comptes")
    else:
        messages.error(request, f"Le changement n'a pu être effectué. Erreur: {result}")
    return redirect('liste_comptes')

def add_to_except_compte(request,id):
    try:
        compte = CompteZoom.objects.get(pk=id)
        compte.is_exception = True
        compte.date_is_exception=timezone.now()
        compte.save()
        return redirect('liste_comptes')
    except Exception as e:
                logging.info(f"Impossible d'ajouter le compte aux comptes a exception{e}" )

@ms_identity_web.login_required
def rapport_licence(request):
    # Logique pour récupérer les données de licence et de comptes Zoom
    result = LicenceDetail.delay()  # Utilisation asynchrone de Celery pour récupérer les détails de licence
    licencedetail = result.get()
    licenseTotal = licencedetail['hosts']
    licenceUtilisé = licencedetail['usage']
    licenceLibre = (licenseTotal - licenceUtilisé)
    comptes_zoom = CompteZoom.objects.all()
    static = CompteZoom.objects.filter(is_static=True).count()
    licenceStatut = ['Licence Total', 'Libre', 'Utilisée', 'Statique']
    licenceNumber = [licenseTotal, licenceLibre, licenceUtilisé, static]

    context = {
        'total_licence': licenseTotal,
        'licenceStatut': licenceStatut,
        'licenceNumber': licenceNumber,
        'licenceUtilisé': licenceUtilisé,
        'licenceLibre': licenceLibre,
        'static': static,
        'comptes_zoom': comptes_zoom,
    }

    # Si la requête est AJAX et GET, gérer le filtrage par intervalle de temps, type de licence et type d'utilisateur
    if request.method == 'GET' and request.headers.get('x-requested-with') == 'XMLHttpRequest':
        # Si la requête est AJAX, récupérer les paramètres de filtrage
        date_start = request.GET.get('date_start')
        date_end = request.GET.get('date_end')
        type_licence = request.GET.get('type_licence')
        type_user = request.GET.get('type_user')

        filters = {}

        # Validation des dates de début et de fin
        if date_start:
            try:
                date_start = datetime.strptime(date_start, '%Y-%m-%d')
            except ValueError:
                return JsonResponse({'error': 'Invalid start date format'}, status=400)

        if date_end:
            try:
                date_end = datetime.strptime(date_end, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
            except ValueError:
                return JsonResponse({'error': 'Invalid end date format'}, status=400)

        # Application des filtres en fonction du type d'utilisateur
        if type_user:
            if type_user == 'Permanent':
                filters['is_static'] = True
                if date_start and date_end:
                    filters['date_static_true__range'] = [date_start, date_end]
            elif type_user == 'Dynamique':
                filters['is_static'] = False
                if date_start and date_end:
                    filters['date_static_false__range'] = [date_start, date_end]
            elif type_user == 'Inactif':
                filters['is_inactif'] = True
                if date_start and date_end:
                    filters['date_inactif__range'] = [date_start, date_end]
            elif type_user == 'exception':
                filters['is_exception'] = True
                if date_start and date_end:
                    filters['date_is_exception__range'] = [date_start, date_end]

        # Application des filtres en fonction du type de licence
        if type_licence:
            filters['label_licence'] = type_licence

        # Application des filtres en fonction de la date de création si aucun type_user n'est sélectionné
        if not type_user and date_start and date_end:
            filters['date_created__range'] = [date_start, date_end]

        # Filtrer les comptes par les critères définis
        comptes_zoom = CompteZoom.objects.filter(**filters)

        # Renvoyer les données filtrées en format JSON
        data = list(comptes_zoom.values('nom', 'email', 'label_licence', 'is_static', 'date_created', 'date_static_true', 'date_static_false', 'is_inactif','auteur'))
        return JsonResponse(data, safe=False)

    # Renvoyer le rendu du template avec le contexte complet
    return render(request, 'rapport_licence.html', context=context)

def bulkMakePermanent(request):
    if request.method == 'POST':
        selected_rows = request.POST.getlist('selected_rows')
        if selected_rows:
            task = celery_bulk_make_permanent.delay(selected_rows)
            # return JsonResponse({'task_id': task.id})
            return JsonResponse({'success': True})
        else:
            messages.error(request, 'Aucune ligne sélectionnée.')
    return redirect('liste_comptes')

def bulkMakeDynamic(request):
    if request.method == 'POST':
        selected_rows = request.POST.getlist('selected_rows')
        if selected_rows:
            task = celery_bulk_make_dynamic.delay(selected_rows)
            return JsonResponse({'task_id': task.id,'success': True})        
        else:
            messages.error(request, 'Aucune ligne sélectionnée.')
    return redirect('liste_comptes')

def bulkAddToExceptionListe(request):
    if request.method == 'POST':
        selected_rows = request.POST.getlist('selected_rows')
        if selected_rows:
            task = celery_bulk_add_toExceptionAccounts.delay(selected_rows)
            # return JsonResponse({'task_id': task.id})
            return JsonResponse({'success': True})
        
        else:
            messages.error(request, 'Aucune ligne sélectionnée.')
    return redirect('liste_comptes')

def bulkRemoveToExceptionListe(request):
    if request.method == 'POST':
        selected_rows = request.POST.getlist('selected_rows')
        if selected_rows:
            task = celery_bulk_Remove_toExceptionAccounts.delay(selected_rows)
            # return JsonResponse({'task_id': task.id})
            return JsonResponse({'success': True})
        
        else:
            messages.error(request, 'Aucune ligne sélectionnée.')
    return redirect('liste_comptes')