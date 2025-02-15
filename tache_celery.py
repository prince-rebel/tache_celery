from celery import shared_task
from django.http import JsonResponse
import logging
from django.utils import timezone
# logging.basicConfig(filename='/home/sbtBurkina/zoomApp/zoom/zoom/zoom_loger.log', level=logging.INFO, format='%(asctime)s - %(message)s')
from .models import CompteZoom, ReunionZoom,Configuration
from django.conf import settings
import requests
from base64 import b64encode
import json
import time
from datetime import datetime, timedelta
from django.db.models import Count
from django.core.mail import send_mail
from django.db.models import Count, Q
from django.utils.timezone import now
from django.conf import settings
from easyaudit.models import CRUDEvent, LoginEvent
import pytz


login_logger = logging.getLogger('django_easy_audit.LoginEvent')
crud_logger = logging.getLogger('django_easy_audit.CRUDEvent')

def get_configuration_values():
    # Valeurs par défaut centralisées
    default_values = {
        'day_before_inactif': 30,
        'number_must_do_inactif': 3,
        'nombre_reunions_minimum': 3,
        'jours_verification': 30
    }

    try:
        config = Configuration.objects.first()
        if config:
            for key in default_values:
                default_values[key] = getattr(config, key, default_values[key])
    except Exception as e:
        logging.warning(f"Erreur lors de la récupération de la configuration: {str(e)}")
    return default_values
       
config_values = get_configuration_values()      
day_before_inactif = config_values['day_before_inactif']
number_must_do_inactif = config_values['number_must_do_inactif']
nombre_reunions_minimum = config_values['nombre_reunions_minimum']
jours_verification = config_values['jours_verification']
date= timezone.now()  



@shared_task
def log_audit_events():
    # Récupérer tous les événements de login
    login_events = LoginEvent.objects.all()
    for event in login_events:
        login_logger.info(f"LoginEvent: {event.user} a connecté à {event.timestamp}")

    # Récupérer tous les événements CRUD
    crud_events = CRUDEvent.objects.all()
    for event in crud_events:
        crud_logger.info(f"CRUDEvent: {event.action} sur {event.content_object} par {event.user} à {event.timestamp}")
        
#************************************************************************************************************************
# def generateToken():
#         userAndPass = b64encode("{}:{}".format(settings.ZOOM_CLIENT_ID, settings.ZOOM_CLIENT_SECRET).encode())
#         headers = {'Host': 'zoom.us',
#                    'Authorization': 'Basic {}'.format(userAndPass.decode("utf-8")),
#                    'Content-Type': 'application/x-www-form-urlencoded',}
#         donnee = 'grant_type=account_credentials&account_id={}'.format(settings.ZOOM_ACCOUND_ID)
#         try:
#                 response = requests.post('https://zoom.us/oauth/token', headers=headers, data=donnee)
#                 test=response.json()
#                 logging.info(f"le token test est {test}")
#                 token=response.json()['access_token']
                
#                 logging.info(f"le token est {token}")
                
#         except Exception as e:
#                 logging.error(f"impossible de generer le token {e}")
#         return token
def generateToken():
    try:
        userAndPass = b64encode(f"{settings.ZOOM_CLIENT_ID}:{settings.ZOOM_CLIENT_SECRET}".encode())
        headers = {
            'Host': 'zoom.us',
            'Authorization': f'Basic {userAndPass.decode("utf-8")}',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        donnee = f'grant_type=account_credentials&account_id={settings.ZOOM_ACCOUND_ID}'
        
        response = requests.post('https://zoom.us/oauth/token', headers=headers, data=donnee)

        # Vérifier si la réponse est valide
        if response.status_code == 200:
            test = response.json()
            logging.info(f"le token test est {test}")
            token = test.get('access_token')
            logging.info(f"le token est {token}")
            return token
        else:
            logging.info(f"Erreur dans la réponse de l'API: {response.status_code}, {response.text}")
            return None

    except Exception as e:
        logging.error(f"Impossible de générer le token: {e}")
        return None


def get_host_Info(host_id):
        try:
                headers = {'authorization': 'Bearer ' + generateToken(),
			'content-type': 'application/json'}
                r =requests.get(f'https://api.zoom.us/v2/users/{host_id}',headers=headers)
                res=r.json()
                code=r.status_code
                logging.debug(code)
                if code == 200:
                        logging.info(f'la requete à reussi, voici les infos {res}')
                else:
                        logging.info(f'la requete pas reussi, voici les infos {res}')
        except Exception as e:
                logging.info("Erreur impossible lors de la recherche des infos du users  {e}")
        return res


@shared_task
# def attribuer_licence_zoomCelery(user_id):
#         headers = {'authorization': 'Bearer ' + generateToken(),
# 			'content-type': 'application/json'}
#         body={
#                 'type':2,
#                 try:
#                 req = requests.patch(f'https://api.zoom.us/v2/users/{user_id}',headers=headers,data=json.dumps(body))
#                 logging.debug(f"*************************Resultat attribution de la licence {req}")
#                 if req.status_code != 202:
#                     logging.debug(f"************************* RAISON Resultat attribution de la licence {req.json()}")
#                 return req.status_code
#         except Exception as e:
#                 logging.debug(f'Erreur lors attribution de la licence {e}')
def attribuer_licence_zoomCelery(user_id):
    logging.info(f"Début du processus d'attribution des licences pour l'utilisateur {user_id}.")

    # Etape 1 : Attribuer le type 2 à l'utilisateur
    logging.info(f"Vérification de l'attribution du type 2 pour l'utilisateur {user_id}.")
    if attribuer_type_2_zoom(user_id):
        logging.info(f"Le type 2 a été attribué avec succès à l'utilisateur {user_id}.")
        logging.info(f"Appel de la fonction pour attribuer la licence Large Meeting 500 à l'utilisateur {user_id}.")
        return attribuer_licence_large_meeting(user_id)
    else:
        logging.error(f"Impossible d'attribuer le type 2 à l'utilisateur {user_id}. Processus d'attribution échoué.")
        return None
 
def attribuer_type_2_zoom(user_id):
    logging.info(f"Début de l'attribution du plan de type 2 à l'utilisateur {user_id}.")

    token = generateToken()
    if not token:
        logging.error("Impossible d'obtenir le token.")
        return False  # Retourne False si le token est introuvable.

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    body = {
        'type': 2  # Attribution du type 2
    }

    try:
        logging.info(f"Envoi de la requête pour attribuer le type 2 à l'utilisateur {user_id}.")
        req = requests.patch(f'https://api.zoom.us/v2/users/{user_id}', headers=headers, data=json.dumps(body))

        if req.status_code <= 204:  # Vérification que le code de statut est <= 204
            logging.info(f"Le plan type 2 a été attribué avec succès à l'utilisateur {user_id}.")
            return True  # Le type 2 a été attribué avec succès, on peut passer à l'étape suivante.
        else:
            logging.error(f"Erreur dans l'attribution du type 2 pour l'utilisateur {user_id}: {req.status_code}, {req.text}")
            return False
    except Exception as e:
        logging.error(f'Erreur lors de l\'attribution du type 2 à l\'utilisateur {user_id}: {e}')
        return False

# Fonction 2 : Attribution de la licence Large Meeting 500
def attribuer_licence_large_meeting(user_id):
    logging.info(f"Début de l'attribution de la licence Large Meeting 500 à l'utilisateur {user_id}.")

    token = generateToken()
    if not token:
        logging.error("Impossible d'obtenir le token.")
        return

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }

    body = {
        "feature": {
            "large_meeting": True,         # Activation de la fonctionnalité Large Meeting
            "large_meeting_capacity": 500  # Capacité de 500 participants
        }
    }

    try:
        logging.info(f"Envoi de la requête pour activer la fonctionnalité Large Meeting 500 pour l'utilisateur {user_id}.")
        req = requests.patch(f'https://api.zoom.us/v2/users/{user_id}/settings', headers=headers, data=json.dumps(body))
        
        logging.info(f"//////////////////////////////////Réponse lors de l'attribution de large meeting à {user_id}: {req.json()}")

        if req.status_code <= 200:
            logging.info(f"Licence Large Meeting 500 attribuée avec succès à l'utilisateur {user_id}.")
        else:
            logging.error(f"Erreur dans l'attribution de la licence Large Meeting pour l'utilisateur {user_id}: {req.status_code}, {req.text}")
        return req.status_code
    except Exception as e:
        logging.error(f'Erreur lors de l\'attribution de la licence Large Meeting à l\'utilisateur {user_id}: {e}')

               

@shared_task
# def retirer_licence_zoomCelery(user_id):
#         headers = {'authorization': 'Bearer ' + generateToken(),
# 			'content-type': 'application/json'}
#         body={
#                 'type':1,
#         }
#         try:
#                 req = requests.patch(f'https://api.zoom.us/v2/users/{user_id}',headers=headers,data=json.dumps(body))
#                 logging.info(f'Revocation  de la licence {req}')
#                 return req.status_code
#         except Exception as e:
#                 logging.info(f'Erreur lors Revocation de la licence {e}')
def retirer_licence_zoomCelery(user_id):
    headers = {
        'authorization': 'Bearer ' + generateToken(),
        'content-type': 'application/json'
    }
    body = {
        'type': 1,
    }
    try:
        req = requests.patch(f'https://api.zoom.us/v2/users/{user_id}', headers=headers, data=json.dumps(body))

        # Vérification du code de statut de la réponse
        if req.status_code == 204:
            logging.info(f"Révocation de la licence réussie pour l'utilisateur {user_id}. Code 204, aucune donnée renvoyée.")
            return req.status_code
        else:
            # Si le code n'est pas 204, afficher tout le JSON renvoyé par l'API
            try:
                error_details = req.json()  # Tente de parser la réponse JSON
                logging.error(f"Erreur lors de la révocation de la licence pour l'utilisateur {user_id}. "
                              f"Code: {req.status_code}. Détails: {json.dumps(error_details, indent=2)}")
            except ValueError:
                # Si la réponse n'est pas au format JSON, afficher le texte brut de la réponse
                logging.error(f"Erreur lors de la révocation de la licence pour l'utilisateur {user_id}. "
                              f"Code: {req.status_code}. Détails: {req.text}")
            return req.status_code

    except requests.exceptions.RequestException as e:
        # Capture des erreurs liées à la requête (problèmes de connexion, timeouts, etc.)
        logging.error(f"Erreur de requête lors de la révocation de la licence pour l'utilisateur {user_id}: {e}")
    except Exception as e:
        # Capture des autres exceptions
        logging.error(f"Erreur inattendue lors de la révocation de la licence pour l'utilisateur {user_id}: {e}")

    return None
                
@shared_task
def start_meeting_task(host_id, meetin_data):
    logging.info('start_meeting_task a démarré')

    identifiant_reunion = meetin_data.get('payload').get('object').get('id')
    sujet_reunion = meetin_data.get('payload').get('object').get('topic')
    user_info = get_host_Info(host_id)

    try:
        test = user_info['email']
        existing_host = CompteZoom.objects.get(email=test)
        if existing_host:
            existing_host.zoom_id = host_id
            existing_host.save()
    except CompteZoom.DoesNotExist:
        # Si l'hôte n'existe pas, créer un nouvel enregistrement
        label_licence = 'licence' if user_info['type'] == 2 else 'Basique'
        date_static_false = timezone.now() if user_info['type'] != 2 else None
        date_static_true = timezone.now() if user_info['type'] == 2 else None
        logging.info(f"---------------------------------le compte n'eiste pas et voici le type du user : {user_info['type']}")
        nouveau_compte = CompteZoom(
            zoom_id=user_info['id'],
            email=user_info['email'],
            nom=user_info['display_name'],
            type=user_info['type'],
            label_licence= label_licence , 
            is_static = False if user_info['type'] != 2 else True,
            date_static_false=date_static_false,
            date_static_true=date_static_true)
        nouveau_compte.save()

        # Tenter d'attribuer une licence
        licence = attribuer_licence_zoomCelery(host_id) if user_info['type'] == 1 else None
        logging.info(f"INFO RETOUR ATTRIBUTION CODE POUR  {user_info['email']} : {licence}")
        if user_info['type'] == 1:
            logging.info(f"INFO RETOUR ATTRIBUTION CODE POUR  {user_info['email']} : {licence}")

            # Vérification que la licence est valide (pas None et <= 204)
            if licence is not None and licence <= 204:
                nouveau_compte.type = 2
                nouveau_compte.label_licence = "licence"
                nouveau_compte.save()
                logging.info(f"La licence a été attribuée avec succès au User {user_info['email']}")
            else:
                logging.error(f"ERREUR: Licence non attribuée ou valeur de licence invalide pour {user_info['email']}")
        else:
            logging.info(f"L'utilisateur {user_info['email']} a déjà une licence. Aucune attribution nécessaire.")

        host_for_meeting = nouveau_compte
    else:
        # Si l'hôte existe déjà
        host_for_meeting = existing_host
        if not host_for_meeting.is_static:
            # Si l'hôte n'est pas statique, essayer d'attribuer une licence
            licence = attribuer_licence_zoomCelery(host_id) 
            if licence is not None and licence <= 204:
                existing_host.type = 2
                existing_host.label_licence = "licence"
                existing_host.save()
                logging.info(f"La licence a été attribuée avec succès à {existing_host.email}")
            else:
                logging.error(f"ERREUR: Licence non attribuée ou valeur de licence invalide pour {existing_host.email}")

    # Vérifier si la réunion existe déjà
    if not ReunionZoom.objects.filter(identifiant=identifiant_reunion).exists():
        nouvelle_reunion = ReunionZoom(
            sujet=sujet_reunion,
            identifiant=identifiant_reunion,
            hote=host_for_meeting,
            heure_debut=timezone.now()
        )
        try:
            nouvelle_reunion.save()
            logging.info(f"Réunion {identifiant_reunion} créée avec succès.")
        except Exception as e:
            logging.error(f"Impossible de sauvegarder la réunion {identifiant_reunion}: {e}")

# def start_meeting_task(host_id,meetin_data):
#         logging.info('start_meeting_task a demarrer')
        
#         # logging.info(f"Event Type est {eventype} programmé par  {meetin_data.get('payload').get('operator')}")
#         identifiant_reunion =meetin_data.get('payload').get('object').get('id')
#         sujet_reunion = meetin_data.get('payload').get('object').get('topic')
#         user_info =get_host_Info(host_id)
#         try:
#                 test = user_info['email']
#                 existing_host  = CompteZoom.objects.get(email=test)
#                 if existing_host:
#                         existing_host.zoom_id = host_id
#                         existing_host.save()
#         except CompteZoom.DoesNotExist:
#                 nouveau_compte =CompteZoom(
#                         zoom_id = user_info['id'],
#                         email =user_info['email'],
#                         nom = user_info['display_name'],
#                         type =user_info['type'],
#                         is_static = False,
#                         date_static_false=timezone.now(),
#                         )
#                 nouveau_compte.save()
#                 licence = attribuer_licence_zoomCelery(host_id)
#                 if licence <= 204:
#                                 nouveau_compte.type = 2
#                                 nouveau_compte.label_licence="licence"
#                                 nouveau_compte.save()
#                                 logging.info(f"**************************La licence a été attribué avec succès au User {user_info['email']}********************************")

#                 host_for_meeting =nouveau_compte
#         else:
#                 host_for_meeting = existing_host
#                 if host_for_meeting.is_static:
#                         pass
#                 else:
#                         licence = attribuer_licence_zoomCelery(host_id)
#                         if licence <= 204:
#                                 existing_host.type = 2
#                                 existing_host.label_licence="licence"
#                                 existing_host.save()
#                                 logging.info(f"La licence a été attribué avec succès ")
#                         else:
#                                 logging.error(f"ERREUR LICENCE PAS ATTRIBUEE {licence}")
                        
#         if not ReunionZoom.objects.filter(identifiant=identifiant_reunion).exists():    
#                  nouvelle_reunion = ReunionZoom(
#                     sujet=sujet_reunion,
#                     identifiant=identifiant_reunion,
#                     hote=host_for_meeting,
#                     heure_debut=timezone.now()
#                 )
#                  try:
#                          nouvelle_reunion.save()
#                  except Exception as e:
#                          logging.error(f"Impossible de sauvegarder la reunion {e}")
                
@shared_task
def revocation_licence(user_id,license_delay):
        existing_host  = CompteZoom.objects.get(zoom_id=user_id)
        logging.info(f"existing_host lors de revocation {existing_host}")
        time.sleep(60*license_delay)
        user_info =retirer_licence_zoomCelery(user_id)
        if user_info == 204:
                existing_host.type=1
                existing_host.save()
                logging.info(f"La licence a été retiré avec succès {user_info}")
                
        else:
                logging.error(f" probleme avec la revocation de la licence {user_info}")

@shared_task
def LicenceDetail():
    
    user_info=sync_zoom_meetings()
        
    try:
        headers = {'authorization': 'Bearer ' + generateToken(),
            'content-type': 'application/json'}
        r= requests.get('https://api.zoom.us/v2/accounts/me/plans/usage',headers=headers)
        res=r.json()
        logging.info(f"Retour du json sur la fonction licencedetail {res}")
        enterprise_plan = None
        if 'plan_bundle' in res:
                bundled_plans = res['plan_bundle']['bundled_plans']
                for plan in bundled_plans:
                        logging.info(f"liste de tous les plans {plan['type']}: {plan['hosts']} : {plan['usage']}")
                        if plan['type'] == 'enterprise_yearly':
                                enterprise_plan = plan
                                break

        if enterprise_plan:
                logging.info(enterprise_plan['type'])
                return enterprise_plan
        
        logging.info(f"Retour du json sur la fonction licencedetail {res}")
        code=r.status_code
        return res['plan_base']
        
    except Exception as e:
        print("ERREUR REQUETE TO GET LICENCE DETAIL",e) 

@shared_task
def send_monthly_reunion_stats_email():
    reunions_par_compte_static = nombre_reunions_par_compte_static_mensuel()
    message = "Statistiques mensuelles des réunions par compte statique :\n\n"
    for reunion in reunions_par_compte_static:
        message += f"{reunion['hote__nom']}: {reunion['total_reunions']} réunions\n"
    
    send_mail(
        'Statistiques mensuelles des réunions',
        message,
        settings.DEFAULT_FROM_EMAIL,
        [settings.ADMIN_EMAIL],  
        fail_silently=False,
    )

def nombre_reunions_par_compte_static_mensuel():
    aujourd_hui = datetime.today()
    premier_jour_du_mois = aujourd_hui.replace(day=1)
    dernier_jour_du_mois_precedent = premier_jour_du_mois - timedelta(days=1)
    premier_jour_du_mois_precedent = dernier_jour_du_mois_precedent.replace(day=1)

    # Filtrer les réunions du mois précédent et compter le nombre de réunions par compte statique
    reunions_par_compte_static = ReunionZoom.objects.filter(
        heure_debut__gte=premier_jour_du_mois_precedent,
        heure_debut__lt=premier_jour_du_mois,
        hote__is_static=True
    ).values('hote__nom').annotate(total_reunions=Count('id'))

    return reunions_par_compte_static

@shared_task
def ajuster_statut_is_static():
    try:
        # Calcul de la date de début pour la vérification
        date_limite = timezone.now() - timedelta(days=jours_verification)

        # Récupération des comptes à ajuster
        comptes_a_ajuster = CompteZoom.objects.filter(is_static=True).annotate(
            num_reunions=Count('reunionzoom', filter=Q(reunionzoom__heure_debut__gte=date_limite))
        )

        for compte in comptes_a_ajuster:
            if compte.num_reunions < nombre_reunions_minimum:
                compte.is_static = False
                compte.date_static_false = timezone.now()
            else:
                compte.is_static = True
                compte.date_static_true =timezone.now()
            compte.save()
            logging.info(f"Statut is_static ajusté pour le compte {compte.email} : {compte.is_static}")

        return f"Ajustement du statut is_static effectué avec succès pour {comptes_a_ajuster.count()} comptes."

    except Exception as e:
        return f"Une erreur s'est produite lors de l'ajustement du statut is_static : {str(e)}"
        
@shared_task
def marquer_compte_comme_inactif():
    try:
        date_limite = timezone.now() - timedelta(days=day_before_inactif)
        logging.info(f'Date limite pour l\'inactivité : {date_limite}')
        comptes_a_ajuster = CompteZoom.objects.exclude(is_inactif=True).exclude(is_exception=True).annotate(
            num_reunions=Count('reunionzoom', filter=Q(reunionzoom__heure_debut__gte=date_limite))
        )

        for compte in comptes_a_ajuster:
            if compte.num_reunions < number_must_do_inactif:
                response_code = retirer_licence_zoomCelery.delay(compte.email)
                if response_code == 204:  
                    compte.is_inactif = True
                    compte.date_inactif = timezone.now()
                    logging.info(f"Compte {compte.email} marqué comme inactif.")
                else:
                    logging.warning(f"Échec de la révocation de la licence pour le compte {compte.email}. Compte non marqué comme inactif.")
            else:
                compte.is_inactif = False
                compte.date_inactif = None
                logging.info(f"Compte {compte.email} reste actif.")
            compte.save()

        return f"Ajustement du statut is_inactif effectué avec succès pour {comptes_a_ajuster.count()} comptes."

    except Exception as e:
        logging.error(f"Une erreur s'est produite lors de l'ajustement du statut is_inactif : {str(e)}")
        return f"Une erreur s'est produite lors de l'ajustement du statut is_inactif : {str(e)}"
    
@shared_task
def UserUpdateFromZoomUsPlateforme(data):
    try:
        logging.info(f"*************************************************Un user a été update c'est {data}")
        
        obj = data.get('payload', {}).get('object', {})
        identifiant = obj.get('id')
        typeLicence = obj.get('type')
        
        req = get_host_Info(identifiant)
        email = req.get('email')
        
        if email:
            test_type_licence =  typeLicence != 1
            is_static = False
            date_now = timezone.now()
            
            compte = CompteZoom.objects.filter(email=email).first()
            if not compte:
                nouveau_compte = CompteZoom(
                    zoom_id=req.get('id'),
                    email=email,
                    nom=req.get('display_name'),
                    type=typeLicence,
                    is_static=is_static,
                    date_static_false=date_now if not is_static else None,
                    date_static_true=date_now if is_static else None,
                    label_licence='Licence' if test_type_licence else 'Basique'
                )
                try:
                    nouveau_compte.save()
                    logging.info(f"Update User from zoom.us: Nouveau compte sauvegardé : {nouveau_compte}")
                except Exception as e:
                    logging.error(f"Update User from zoom.us:Impossible de sauvegarder le compte : {e}")
            else:
                try:
                    compte.type = typeLicence
                    compte.is_static = is_static
                    compte.zoom_id=req.get('id')
                    if is_static:
                        compte.date_static_true = date_now
                        compte.date_static_false = None
                        compte.label_licence = 'Licence'
                    else:
                        compte.date_static_false = date_now
                        compte.date_static_true = None
                        compte.label_licence = 'Licence' if test_type_licence else 'Basique'
                    
                    compte.save()
                    logging.info(f"Update User from zoom.us: Compte mis à jour : {compte}")
                except Exception as e:
                    logging.error(f"Update User from zoom.us:Impossible de mettre à jour le compte : {e}")
        else:
            logging.info("Update User from zoom.us:L'email est manquant dans les données reçues.")
    
    except Exception as e:
        logging.error(f"Erreur lors de la mise à jour des informations de l'utilisateur : {e}")
        
@shared_task
def celery_bulk_make_permanent(selected_rows):
    comptes = CompteZoom.objects.filter(id__in=selected_rows)
    emails = list(comptes.values_list('email', flat=True))
    # comptes.update(is_static=True, label_licence='Licence', date_static_true=timezone.now())
    results = []
    for email in emails:
        attribuer_licence = attribuer_licence_zoomCelery.delay(email)
        if attribuer_licence.get(timeout=10) <= 204:  
            logging.info(f'Licence attribuée avec succès à l\'email : {email}')
            results.append(True)
            comptes.filter(email=email).update(
                is_static=True,
                label_licence='Licenced',
                date_static_true=datetime.now()
            )
        else:
            logging.error(f"Échec de l'attribution de licence pour l'email : {email}")
            results.append(False)
    if all(results):
        return {'status': 'completed'}
    else:
        return {'status': 'failed'}

@shared_task
def celery_bulk_make_dynamic(selected_rows):
    comptes = CompteZoom.objects.filter(id__in=selected_rows)
    logging.info(f'Comptes à traiter : {comptes}')
    emails = list(comptes.values_list('email', flat=True))
    results = []

    for email in emails:
        retirer_licence = retirer_licence_zoomCelery.delay(email)
        try:
            if retirer_licence.get(timeout=10) == 204:  
                logging.info(f'Licence retirée avec succès pour l\'email : {email}')
                results.append(True)
                
                comptes.filter(email=email).update(
                    is_static=False,
                    label_licence='Basique',
                    date_static_false=timezone.now(),
                )
            else:
                logging.error(f"Échec du retrait de licence pour l'email : {email}")
                results.append(False)
        except Exception as e:
            logging.error(f'Erreur lors du retrait de la licence pour l\'email {email} : {e}')
            results.append(False)

    if all(results):
        return {'status': 'completed'}
    else:
        return {'status': 'failed'}

@shared_task
def celery_bulk_add_toExceptionAccounts(selected_rows):
    comptes = CompteZoom.objects.filter(id__in=selected_rows)
    comptes.update(is_exception=True,date_is_exception=date)
    return {'status': 'completed'}

@shared_task
def celery_bulk_Remove_toExceptionAccounts(selected_rows):
    comptes = CompteZoom.objects.filter(id__in=selected_rows)
    comptes.update(is_exception=False)
    return {'status': 'completed'}




def get_or_create_host(email, zoom_id):
    """
    Vérifie si un hôte existe dans la base de données.
    S'il n'existe pas, crée un nouveau CompteZoom.
    """
    try:
        return CompteZoom.objects.get(email=email)
    except CompteZoom.DoesNotExist:
        # Créer un compte par défaut si l'utilisateur n'existe pas
        return CompteZoom.objects.create(
            email=email,
            zoom_id=zoom_id,
            nom="Inconnu",  # Valeur par défaut
            label_licence="Standard",  # Valeur par défaut
            type=1  # Valeur par défaut
        )

# --- 2. Fonction pour récupérer les réunions via l'API Zoom ---
def fetch_organization_meetings():
    """
    Récupère toutes les réunions de l'organisation des dernières 24 heures via l'API Zoom.
    """
    url = "https://api.zoom.us/v2/metrics/meetings"
    headers = {"Authorization": "Bearer" + generateToken()}
    now = datetime.utcnow()
    last_24_hours = now - timedelta(days=1)
    params = {
        "type": "live",  # Réunions passées
        "from": last_24_hours.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "to": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "page_size": 100
    }

    meetings = []
    try:
        while True:
            logging.info("Envoi de la requête à l'API Zoom pour récupérer les réunions.")
            response = requests.get(url, headers=headers, params=params)
            if response.status_code != 200:
                raise Exception(f"Erreur API Zoom: {response.status_code} - {response.text}")
            data = response.json()
            logging.info(f"Réponse API reçue avec {len(data.get('meetings', []))} réunions.")
            meetings.extend(data.get("meetings", []))
            if not data.get("next_page_token"):
                break
            params["next_page_token"] = data["next_page_token"]

    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur de connexion à l'API Zoom: {e}")
        raise
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des réunions: {e}")
        raise

    # Log des données récupérées
    logging.info(f"Nombre total de réunions récupérées: {len(meetings)}")
    for meeting in meetings:
        logging.info(
            f"Réunion ID: {meeting.get('id')}, Sujet: {meeting.get('topic')}, "
            f"Hôte: {meeting.get('host')}, Email: {meeting.get('email')}, "
            f"Début: {meeting.get('start_time')}, Participants: {meeting.get('participants')}"
        )

    return meetings

# --- Fonction pour sauvegarder une réunion (placeholder à adapter pour la base de données) ---

def fetch_organization_meetings_terminées():
    """
    Récupère toutes les réunions terminées de l'organisation des dernières 24 heures via l'API Zoom.
    """
    url = "https://api.zoom.us/v2/metrics/meetings"
    headers = {"Authorization": "Bearer " + generateToken()}
    now = datetime.utcnow()
    last_24_hours = now - timedelta(days=1)
    params = {
        "type": "past",  # Réunions terminées
        "from": last_24_hours.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "to": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "page_size": 100
    }

    meetings = []
    try:
        while True:
            logging.info("Envoi de la requête à l'API Zoom pour récupérer les réunions terminées.")
            response = requests.get(url, headers=headers, params=params)
            if response.status_code != 200:
                raise Exception(f"Erreur API Zoom: {response.status_code} - {response.text}")
            data = response.json()
            logging.info(f"Réponse API reçue avec {len(data.get('meetings', []))} réunions.")
            meetings.extend(data.get("meetings", []))
            if not data.get("next_page_token"):
                break
            params["next_page_token"] = data["next_page_token"]

    except requests.exceptions.RequestException as e:
        logging.error(f"Erreur de connexion à l'API Zoom: {e}")
        raise
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des réunions: {e}")
        raise

    # Log des données récupérées
    logging.info(f"Nombre total de réunions terminé récupérées: {len(meetings)}")
    for meeting in meetings:
        logging.info(
            f"Réunion ID: {meeting.get('id')}, Sujet: {meeting.get('topic')}, "
            f"Hôte: {meeting.get('host')}, Email: {meeting.get('email')}, "
            f"Début: {meeting.get('start_time')}, Fin: {meeting.get('end_time')}"
        )

    return meetings

def save_meeting(meeting_data):
    """
    Sauvegarde une réunion dans la base de données après récupération des infos de l'hôte.
    """
    try:
        host_email = meeting_data.get("email")
        host_info = get_host_Info(host_email)

        # Log des informations sur l'hôte
        logging.info(f"Informations de l'hôte (email: {host_email}): {host_info}")

        identifiant = meeting_data.get("id")
        sujet = meeting_data.get("topic")
        
        # Conversion de `start_time` au format datetime
        heure_debut = meeting_data.get("start_time")
        heure_fin = meeting_data.get("end_time", None)

        if heure_debut:
            try:
                # Convertir `start_time` en objet datetime
                heure_debut = datetime.strptime(heure_debut, "%Y-%m-%dT%H:%M:%SZ")
                heure_debut = heure_debut.replace(tzinfo=pytz.UTC)  # Assurez-vous que la timezone est UTC
            except ValueError:
                logging.error(f"Format invalide pour start_time : {heure_debut}")
                raise

        # Si `end_time` est vide, créer une variable `current_time` pour l'heure actuelle
        if not heure_fin:  # La réunion est en cours
            current_time = datetime.utcnow().replace(tzinfo=pytz.UTC)  # Prendre l'heure actuelle (UTC)
            duree = (current_time - heure_debut).seconds / 60  # Durée en minutes
            heure_fin = None  # Ne pas mettre de valeur pour `end_time`
        else:
            try:
                # Convertir `end_time` en objet datetime si la valeur est spécifiée
                heure_fin = datetime.strptime(heure_fin, "%Y-%m-%dT%H:%M:%SZ")
                heure_fin = heure_fin.replace(tzinfo=pytz.UTC)
                duree = (heure_fin - heure_debut).seconds / 60  # Durée en minutes
            except ValueError:
                logging.error(f"Format invalide pour end_time : {heure_fin}")
                raise

        # Log des données à sauvegarder
        logging.info(
            f"Sauvegarde de la réunion ID: {identifiant}, Sujet: {sujet}, "
            f"Hôte: {host_email}, Début: {heure_debut}, Fin: {heure_fin}, "
            f"Durée: {duree} minutes"
        )

        # Vérification de l'existence de l'hôte dans la table CompteZoom
        compte_zoom = CompteZoom.objects.filter(email=host_email).first()

        if compte_zoom:
            # Si l'hôte existe déjà, on utilise l'instance existante
            logging.info(f"L'hôte {host_email} existe déjà dans la table CompteZoom.")
        else:
            
            # Si l'hôte n'existe pas, on crée une nouvelle instance de CompteZoom
            logging.info(f"L'hôte {host_email} n'existe pas dans la table CompteZoom. Création nécessaire.")
            compte_zoom = CompteZoom.objects.create(
                email=host_email,
                first_name=host_info.get("first_name", ""),
                last_name=host_info.get("last_name", ""),
                type="Basic",  # Exemple : le type de l'hôte est "Basic" par défaut
                is_static=False  # Par défaut ou selon votre logique
            )

        # Sauvegarde ou mise à jour des données de la réunion
        ReunionZoom.objects.update_or_create(
            identifiant=identifiant,
            defaults={  # Données à sauvegarder
                "sujet": sujet,
                "hote": compte_zoom,  # Assigner l'instance `CompteZoom` au champ `hote`
                "heure_debut": heure_debut,
                "heure_fin": heure_fin,  # Si `end_time` est vide, `heure_fin` restera vide
                "duree": duree,
            }
        )

    except Exception as e:
        logging.error(f"Erreur lors de la sauvegarde de la réunion : {e}")
        raise
    
def save_meeting_terminée(meeting_data):
    """
    Sauvegarde une réunion terminée dans la base de données après récupération des infos de l'hôte.
    """
    try:
        host_email = meeting_data.get("email")
        host_info = get_host_Info(host_email)

        # Log des informations sur l'hôte
        logging.info(f"Informations de l'hôte (email: {host_email}): {host_info}")

        identifiant = meeting_data.get("id")
        sujet = meeting_data.get("topic")
        
        # Conversion de `start_time` au format datetime
        heure_debut = meeting_data.get("start_time")
        heure_fin = meeting_data.get("end_time", None)

        if heure_debut:
            try:
                # Convertir `start_time` en objet datetime
                heure_debut = datetime.strptime(heure_debut, "%Y-%m-%dT%H:%M:%SZ")
                heure_debut = heure_debut.replace(tzinfo=pytz.UTC)  # Assurez-vous que la timezone est UTC
            except ValueError:
                logging.error(f"Format invalide pour start_time : {heure_debut}")
                raise

        if heure_fin:  # Si `end_time` est précisé, on le convertit également
            try:
                # Convertir `end_time` en objet datetime si la valeur est spécifiée
                heure_fin = datetime.strptime(heure_fin, "%Y-%m-%dT%H:%M:%SZ")
                heure_fin = heure_fin.replace(tzinfo=pytz.UTC)
                duree = (heure_fin - heure_debut).seconds / 60  # Durée en minutes
            except ValueError:
                logging.error(f"Format invalide pour end_time : {heure_fin}")
                raise
        else:
            logging.warning(f"Réunion ID {identifiant} n'a pas de `end_time`. Cela devrait être vérifié.")
            duree = None  # La réunion a une durée indéterminée si `end_time` n'est pas fourni

        # Log des données à sauvegarder
        logging.info(
            f"Sauvegarde de la réunion ID: {identifiant}, Sujet: {sujet}, "
            f"Hôte: {host_email}, Début: {heure_debut}, Fin: {heure_fin}, "
            f"Durée: {duree} minutes"
        )

        # Vérification de l'existence de l'hôte dans la table CompteZoom
        compte_zoom = CompteZoom.objects.filter(email=host_email).first()

        if compte_zoom:
            # Si l'hôte existe déjà, on utilise l'instance existante
            logging.info(f"L'hôte {host_email} existe déjà dans la table CompteZoom.")
        else:
            # Si l'hôte n'existe pas, on crée une nouvelle instance de CompteZoom
            user_info = get_host_Info(host_id)
            logging.info(f"  creation des comptes apres recuperations de reunions---------------------------L'hôte {host_email} n'existe pas dans la table CompteZoom. Création nécessaire. voici son type {user_info['type']} ")
           
            
            compte_zoom = CompteZoom.objects.create(
                email=host_email,
                first_name=host_info.get("first_name", ""),
                last_name=host_info.get("last_name", ""),
                type="Basic",  # Exemple : le type de l'hôte est "Basic" par défaut
                is_static=False  # Par défaut ou selon votre logique
            )

        # Vérification de l'existence de la réunion dans la base de données
        reunion = ReunionZoom.objects.filter(identifiant=identifiant).first()

        if reunion:
            # Si la réunion existe déjà, on met à jour l'heure de fin
            reunion.heure_fin = heure_fin
            reunion.duree = duree
            reunion.save()
            logging.info(f"Réunion {identifiant} mise à jour avec l'heure de fin.")
        else:
            # Sinon, on crée une nouvelle réunion avec les données
            ReunionZoom.objects.create(
                identifiant=identifiant,
                sujet=sujet,
                hote=compte_zoom,  # Assigner l'instance `CompteZoom` au champ `hote`
                heure_debut=heure_debut,
                heure_fin=heure_fin,
                duree=duree,
            )
            logging.info(f"Nouvelle réunion {identifiant} créée.")

    except Exception as e:
        logging.error(f"Erreur lors de la sauvegarde de la réunion terminée : {e}")
        raise
# --- Fonction orchestrant la synchronisation ---
def sync_zoom_meetings():
    """
    Synchronise toutes les réunions Zoom de l'organisation avec la base de données.
    """
    try:
        # Récupérer les réunions en cours
        live_meetings = fetch_organization_meetings()

        # Récupérer les réunions terminées
        past_meetings = fetch_organization_meetings_terminées()

        # Sauvegarder les réunions en cours
        for meeting in live_meetings:
            save_meeting(meeting)

        # Sauvegarder les réunions terminées
        for meeting in past_meetings:
            save_meeting_terminée(meeting)

        logging.info("Synchronisation des réunions terminée avec succès.")
    except Exception as e:
        logging.error(f"Erreur lors de la synchronisation des réunions: {e}")

# Lancement direct
if __name__ == "__main__":
    sync_zoom_meetings()