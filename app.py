import eventlet
eventlet.monkey_patch()

import json
import os
from flask import Flask, render_template, request, redirect, session, url_for, flash, Response, jsonify
from supabase import create_client, Client
from postgrest.exceptions import APIError
from dotenv import load_dotenv
from datetime import datetime, date, time, timedelta  # Importamos tanto datetime como date, time y timedelta
import pytz  # Para manejo de zonas horarias
from queue import Queue, Empty # <-- Importa la clase Queue
# 👇 AÑADIR ESTAS DOS importaciones para hashear contraseñas
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import requests
import re

# Cargar variables de entorno
load_dotenv()

# Configurar Flask
app = Flask(__name__)
app.secret_key = "novaglez"  # cambia por algo seguro en producción

# Configurar Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"Error initializing Supabase client: {e}")
    supabase = None

# # --- AÑADE ESTE BLOQUE DE DEBUG ---
# print("=============================================")
# print("=== VERIFICANDO CLAVES DE SUPABASE ===")
# if SUPABASE_KEY and len(SUPABASE_KEY) > 100:
#     print(f"URL: {SUPABASE_URL}")
#     print(f"CLAVE DETECTADA (parcial): {SUPABASE_KEY[:10]}...{SUPABASE_KEY[-5:]}")
#     print("PARECE SER LA SERVICE_ROLE KEY (por su longitud).")
# else:
#     print("¡ADVERTENCIA! LA CLAVE CARGADA ES CORTA. ¿ESTÁS SEGURO DE QUE ES LA SERVICE_ROLE KEY?")
# print("=============================================")
# # --- FIN DEL BLOQUE DE DEBUG ---


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
WHATSAPP_API_URL = os.getenv("WHATSAPP_API_URL")


def send_telegram_message(message):
    """Envía un mensaje al grupo de Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error al enviar mensaje a Telegram: {e}")

def send_whatsapp_reminder(recipient_phone, patient_name, date_str):
    # --- INICIO DE LA MODIFICACIÓN ---
    # Validamos y formateamos la fecha antes de enviarla.
    # Se asume que 'date_str' llega en formato 'YYYY-MM-DD'.
    try:
        # 1. Convertir la cadena de texto a un objeto de fecha (datetime)
        fecha_obj = datetime.strptime(date_str, '%Y-%m-%d')
        # 2. Formatear ese objeto al nuevo formato 'DD-MM-YYYY'
        fecha_formateada = fecha_obj.strftime('%d-%m-%Y')
    except (ValueError, TypeError):
        # Si por alguna razón la fecha no viene en el formato esperado,
        # usamos la cadena original para no causar un error.
        print(f"Advertencia: Formato de fecha inesperado ('{date_str}'). Se usará el valor original.")
        fecha_formateada = date_str
    """Envía un recordatorio de cita vía WhatsApp usando la API de WhatsApp Business."""
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "template",
        "template": {
            "name": "cita_medica_registrada",  # nombre exacto de tu plantilla
            "language": {
            "code": "es_DO"
            },
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": fecha_formateada},
                        {"type": "text", "text": patient_name}
                    ]
                }
            ]
        }
    }

    #response = requests.post(url, headers=headers, json=payload)

    #print("Status code:", response.status_code)
    #print("Response:", json.dumps(response.json(), indent=2, ensure_ascii=False))
    try:
        #print(ACCESS_TOKEN)

        url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
        response = requests.post(url, headers=headers, json=payload)

        print("Status code:", response.status_code)
        #print("Response:", json.dumps(response.json(), indent=2, ensure_ascii=False))
        
        #response = requests.post(f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages", headers=headers, json=payload, timeout=20)
        #response.raise_for_status()
        print(f"✅ Recordatorio enviado a {patient_name} ({recipient_phone}). Status: {response.status_code}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al enviar mensaje a {patient_name} ({recipient_phone}): {e}")
        if e.response is not None:
            print("Error detallado de la API:", e.response.json())
        return False

def send_whatsapp_reminder_secretaria(full_name, telefono, fecha_cita, motivo_consulta, numero_seguro_medico, nombre_seguro_medico):
    """Envía un recordatorio de cita vía WhatsApp usando la API de WhatsApp Business."""
    
    # Validamos y formateamos la fecha antes de enviarla.
    try:
        fecha_obj = datetime.strptime(fecha_cita, '%Y-%m-%d')
        fecha_cita = fecha_obj.strftime('%d-%m-%Y')
    except (ValueError, TypeError):
        print(f"Advertencia: Formato de fecha inesperado ('{fecha_cita}'). Se usará el valor original.")
    
    # Asegurar que ningún parámetro sea None o vacío (la API de WhatsApp no acepta valores vacíos)
    full_name = str(full_name).strip() if full_name else "No especificado"
    telefono = str(telefono).strip() if telefono else "No especificado"
    fecha_cita = str(fecha_cita).strip() if fecha_cita else "No especificado"
    motivo_consulta = str(motivo_consulta).strip() if motivo_consulta else "No especificado"
    numero_seguro_medico = str(numero_seguro_medico).strip() if numero_seguro_medico else "No especificado"
    nombre_seguro_medico = str(nombre_seguro_medico).strip() if nombre_seguro_medico else "No especificado"
    
    # Debug: imprimir los valores que se enviarán
    print(f"DEBUG Secretaria - Params: name='{full_name}', tel='{telefono}', fecha='{fecha_cita}', motivo='{motivo_consulta}', num_seguro='{numero_seguro_medico}', nombre_seguro='{nombre_seguro_medico}'")
        
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    recipient_phone = "8097695217" # Número de la secretaria
    #recipient_phone = "8299691469" # Número de la secretaria

    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "template",
        "template": {
            "name": "notificacion_cita_registrada",
            "language": {"code": "es_DO"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "parameter_name": "full_name", "text": full_name},
                        {"type": "text", "parameter_name": "telefono", "text": telefono},
                        {"type": "text", "parameter_name": "fecha_cita", "text": fecha_cita},
                        {"type": "text", "parameter_name": "motivo_consulta", "text": motivo_consulta},
                        {"type": "text", "parameter_name": "numero_seguro_medico", "text": numero_seguro_medico},
                        {"type": "text", "parameter_name": "nombre_seguro_medico", "text": nombre_seguro_medico}
                    ]
                }
            ]
        }
    }

    # Cita médica registrada con éxito.

    # *Nombre del paciente:*  {{full_name}}
    # *Teléfono:* {{telefono}}
    # *Fecha:* {{fecha_cita}}
    # *Motivo:*  {{motivo_consulta}}
    # *Número de Seguro Médico: * {{numero_seguro_medico}}
    # *Nombre del Seguro Médico: * {{nombre_seguro_medico}}

    # *Notificación de cita médica registrada.*

    #response = requests.post(url, headers=headers, json=payload)

    #print("Status code:", response.status_code)
    #print("Response:", json.dumps(response.json(), indent=2, ensure_ascii=False))
    try:
        url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
        response = requests.post(url, headers=headers, json=payload)

        print("Status code:", response.status_code)
        if response.status_code != 200:
            print("Response Error:", response.json())
        
        print(f"✅ Recordatorio enviado a {full_name} ({recipient_phone}). Status: {response.status_code}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al enviar mensaje a {full_name} ({recipient_phone}): {e}")
        if e.response is not None:
            print("Error detallado de la API:", e.response.json())
        return False


# Crea una cola para almacenar los anuncios de pacientes.
# Esta cola es segura para usar entre diferentes peticiones.
announcement_queue = Queue()

# --- DECORADORES PARA PROTECCIÓN DE RUTAS ---

def public_route(f):
    """Marca una ruta como pública (no requiere autenticación)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        return f(*args, **kwargs)
    return decorated_function

def role_required(*roles):
    """Protege una ruta requiriendo un rol específico"""
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 1. Verificar si el usuario ha iniciado sesión
            if 'usuario' not in session:
                flash("⚠️ Debes iniciar sesión para acceder a esta página.", "error")
                return redirect(url_for('login'))
            
            # 2. Verificar si el rol del usuario está permitido en esta ruta
            if roles and session.get('role') not in roles:
                flash("🚫 No tienes permiso para acceder a esta sección.", "error")
                # Redirigir al panel correspondiente según su rol
                if session.get('role') == 'admin':
                    return redirect(url_for('admin'))
                else:
                    return redirect(url_for('secretaria_dashboard'))

            return f(*args, **kwargs)
        return decorated_function
    return wrapper


@app.route("/dias_llenos", methods=["GET", "POST"])
def dias_llenos():
    """
    Devuelve la cantidad de citas agrupadas por fecha,
    filtrando solo desde la fecha actual en adelante.
    
    Returns:
        list: [{"fecha": "YYYY-MM-DD", "cantidad": int}, ...]
    """
    hoy = date.today().isoformat()  # Fecha actual en formato YYYY-MM-DD
    
    # Traemos todas las citas con fecha >= hoy
    response = supabase.table("citas").select("fecha").gte("fecha", hoy).execute()
    citas = response.data
    
    # Contamos por fecha
    conteo = {}
    for cita in citas:
        fecha = cita["fecha"]
        conteo[fecha] = conteo.get(fecha, 0) + 1
    
    # Convertimos a lista ordenada por fecha
    resultado = [{"fecha": f, "cantidad": c} for f, c in sorted(conteo.items())]
    
    return resultado

# --- FUNCIÓN AUXILIAR PARA OBTENER CONFIGURACIÓN (ACTUALIZADA) ---
def get_configuracion():
    """Obtiene la configuración de la BD y la devuelve como un diccionario con valores por defecto."""
    try:
        config_data = supabase.table("configuracion").select("clave, valor").execute().data
        config = {item['clave']: item['valor'] for item in config_data}
    except Exception as e:
        print(f"Error obteniendo configuración: {e}")
        config = {}
    
    # Asegurarse de que las claves siempre existan
    config.setdefault('bloquear_sabados', 'false')
    config.setdefault('bloquear_domingos', 'false')
    # NUEVO: Valores por defecto para límites de pacientes (un número alto significa sin límite)
    dias = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado']
    for dia in dias:
        config.setdefault(f'max_pacientes_{dia}', '999') # 999 como "infinito"
    return config

# --- FUNCIÓN MEJORADA PARA OBTENER DÍAS LLENOS ---
def get_dias_llenos(config=None):
    """
    Consulta las citas, las agrupa por fecha y devuelve una lista de fechas
    que han alcanzado su límite de pacientes según la configuración.
    Solo considera fechas futuras.
    """
    if config is None:
        config = get_configuracion()
    dias_llenos = []
    
    # Mapeo de weekday() a claves de configuración (Lunes=0, Domingo=6)
    mapa_dias = {
        0: 'lunes', 1: 'martes', 2: 'miercoles',
        3: 'jueves', 4: 'viernes', 5: 'sabado'
    }

    try:
        # Traemos todas las citas con fecha
        response = supabase.table("citas").select("fecha").execute()
        citas = response.data
        
        # Contamos por fecha manualmente en Python
        conteo = {}
        for cita in citas:
            fecha = cita["fecha"]
            conteo[fecha] = conteo.get(fecha, 0) + 1
        
# Convertimos a lista ordenada por fecha
        citas_por_dia = [{"fecha": f, "cantidad": c} for f, c in sorted(conteo.items())]
        
        for item in citas_por_dia:
            fecha_str = item['fecha']
            cantidad = item['cantidad']
             
            fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
            dia_semana = fecha_obj.weekday() # Lunes=0, Martes=1, ...
            
            if dia_semana in mapa_dias:
                nombre_dia = mapa_dias[dia_semana]
                try:
                    limite = int(config.get(f'max_pacientes_{nombre_dia}', 999))
                    # Si el cantidad alcanza o supera el límite, agregar a días llenos
                    if cantidad >= limite:
                        dias_llenos.append(fecha_str)
                except (ValueError, TypeError):
                    print(f"Error: El límite para {nombre_dia} no es un número válido")

    except Exception as e:
        print(f"Error calculando días llenos: {e}")

    return dias_llenos

def verificar_cita_duplicada(fecha_str, cedula_raw, nombre, telefono):
    """
    Verifica si ya existe una cita para el mismo paciente y fecha.
    Retorna True si existe duplicado, False si es seguro continuar.
    """
    try:
        # Construimos la consulta base para la fecha
        query = supabase.table("citas").select("id", count='exact').eq("fecha", fecha_str)

        # Añadimos el identificador del paciente a la consulta
        if cedula_raw:
            # Si hay cédula, es el mejor identificador
            query = query.eq("cedula", cedula_raw)
        else:
            # Si no, usamos la combinación de nombre y teléfono
            query = query.eq("nombre", nombre).eq("telefono", telefono)
        
        # Ejecutamos la consulta
        existing_cita_result = query.execute()

        # Si el contador es mayor que 0, ya existe una cita
        return existing_cita_result.count > 0

    except Exception as e:
        print(f"Error al verificar cita duplicada: {e}")
        # En caso de error, permitimos continuar (no bloqueamos)
        return False
    
# @app.route("/admin/configuracion", methods=["GET", "POST"])
# @role_required('admin')  # Solo administradores pueden acceder aquí
# def configuracion():
#     if "usuario" not in session:
#         flash("⚠️ Debes iniciar sesión para acceder", "error")
#         return redirect(url_for("login"))

#     # Definimos los servicios en un solo lugar para usarlos tanto en GET como en POST.
#     # Esta es nuestra "única fuente de verdad" para los tipos de consulta.
#     servicios = [
#         ('ginecologica', 'Consulta ginecológica'),
#         ('mama', 'Consulta de mama'),
#         ('post', 'Post quirúrgico'),
#         ('biopsia', 'Biopsia'),
#         ('resultados', 'Entrega de resultados')
#     ]
        
#     if request.method == "POST":
#         # --- Lógica existente para bloqueos y límites (sin cambios) ---
#         sabados_bloqueados = 'true' if 'bloquear_sabados' in request.form else 'false'
#         domingos_bloqueados = 'true' if 'bloquear_domingos' in request.form else 'false'
        
#         dias = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado']
#         config_updates = [
#             {'clave': 'bloquear_sabados', 'valor': sabados_bloqueados},
#             {'clave': 'bloquear_domingos', 'valor': domingos_bloqueados}
#         ]
#         for dia in dias:
#             limite = request.form.get(f'max_pacientes_{dia}')
#             valor_a_guardar = limite if limite else '999'
#             config_updates.append({'clave': f'max_pacientes_{dia}', 'valor': valor_a_guardar})

#         # --- NUEVA LÓGICA PARA GUARDAR PRECIOS ---
#         # Recorremos la lista de servicios y obtenemos el precio de cada uno desde el formulario.
#         for key, _ in servicios:
#             # Creamos la clave de la base de datos, ej: "precio_ginecologica"
#             clave_precio = f'precio_{key}'
#             # Obtenemos el valor del formulario. Si está vacío, guardamos una cadena vacía.
#             valor_precio = request.form.get(clave_precio, '')
#             config_updates.append({'clave': clave_precio, 'valor': valor_precio})
        
#         # Guardamos todas las actualizaciones (límites, bloqueos y precios) en una sola llamada.
#         try:
#             supabase.table('configuracion').upsert(config_updates, on_conflict='clave').execute()
#             flash("✅ Configuración guardada correctamente.", "success")
#         except Exception as e:
#             flash(f"❌ Error al guardar la configuración: {e}", "error")
            
#         return redirect(url_for('configuracion'))

#     # Para el método GET, obtenemos la configuración y la pasamos al template,
#     # incluyendo ahora la lista de servicios para construir el formulario dinámicamente.
#     config = get_configuracion()
#     return render_template("configuracion.html", configuracion=config, servicios=servicios)

@app.route("/admin/configuracion", methods=["GET", "POST"])
@role_required('admin')
def configuracion():
    if request.method == "POST":
        # --- Lógica para guardar bloqueos y límites (sin cambios) ---
        sabados_bloqueados = 'true' if 'bloquear_sabados' in request.form else 'false'
        domingos_bloqueados = 'true' if 'bloquear_domingos' in request.form else 'false'
        
        dias = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado']
        config_updates = [
            {'clave': 'bloquear_sabados', 'valor': sabados_bloqueados},
            {'clave': 'bloquear_domingos', 'valor': domingos_bloqueados}
        ]
        for dia in dias:
            limite = request.form.get(f'max_pacientes_{dia}')
            valor_a_guardar = limite if limite else '999'
            config_updates.append({'clave': f'max_pacientes_{dia}', 'valor': valor_a_guardar})

        # Guardamos solo las configuraciones generales
        try:
            supabase.table('configuracion').upsert(config_updates, on_conflict='clave').execute()
            flash("✅ Configuración general guardada correctamente.", "success")
        except Exception as e:
            flash(f"❌ Error al guardar la configuración: {e}", "error")
            
        return redirect(url_for('configuracion'))

    # --- Lógica GET (Modificada) ---
    # 1. Obtener configuración general
    config = get_configuracion()
    # 2. Obtener la lista de servicios desde la nueva tabla
    servicios = []
    try:
        servicios = supabase.table("servicios").select("*").order("nombre").execute().data
    except Exception as e:
        flash(f"❌ Error al cargar la lista de servicios: {e}", "error")
    
    return render_template("configuracion.html", configuracion=config, servicios=servicios)

@app.route("/", methods=["GET", "POST"])
@public_route
def pagina_principal():
    # Datos extraídos de la imagen para pasarlos a la plantilla.
    # Esto hace que sea más fácil de mantener que escribirlos directo en el HTML.
    doctora_info = {
        "nombre": "Dra. Jennifer Reyes M.",
        "especialidades": "Ginecología-Obstetricia, Mastología",
        "telefono_movil": "(829)-642-1564",
        "telefono_fijo": "(809)-244-6300, Ext. 718",
        "direccion": "Torre Ejecutiva Siglo 21, 5to. Nivel, Suite 501",
        "email": "dra.jenniferreyes@hotmail.com",
        "imagen_url": "/static/images/dra-jennifer-reyes.png" # Asegúrate de tener una imagen en esta ruta
    }
    # Renderiza la nueva plantilla 'index.html' y le pasa los datos.
    return render_template("index.html", doctora=doctora_info)

#registra cita 
@app.route("/cita", methods=["GET", "POST"])
@public_route
def registrar_cita():
    # --- Configuración inicial ---
    config = get_configuracion()

    # --- Fechas bloqueadas manualmente ---
    try:
        fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
        fechas_bloqueadas_manualmente = {f["fecha"] for f in fechas_bloqueadas_data}
    except Exception as e:
        print(f"Error al obtener fechas bloqueadas: {e}")
        fechas_bloqueadas_manualmente = set()

    # --- Días llenos por configuración ---
    dias_llenos = set(get_dias_llenos(config))

    # --- Unificar todas las fechas no disponibles ---
    fechas_no_disponibles = list(fechas_bloqueadas_manualmente.union(dias_llenos))

    # --- Si el usuario envía el formulario (POST) ---
    if request.method == "POST":
        fecha_str = request.form["fecha"]
        try:
            fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            flash("❌ La fecha seleccionada no es válida.", "error")
            return redirect(url_for("registrar_cita"))

# --- Validaciones de fechas ---
        if config.get('bloquear_sabados') == 'true' and fecha_obj.weekday() == 5:
            flash("❌ No se pueden agendar citas los sábados.", "error")
            return redirect(url_for("registrar_cita"))

        if config.get('bloquear_domingos') == 'true' and fecha_obj.weekday() == 6:
            flash("❌ No se pueden agendar citas los domingos.", "error")
            return redirect(url_for("registrar_cita"))

        # --- Validación de hora para día actual (República Dominicana) ---
        try:
            # Obtener hora actual en zona horaria de República Dominicana (AST/UTC-4)
            zona_rd = pytz.timezone('America/Santo_Domingo')
            hora_actual_rd = datetime.now(zona_rd)
            
            # Verificar si la fecha seleccionada es hoy
            hoy_rd = hora_actual_rd.date()
            
            if fecha_obj == hoy_rd:
                # Si es hoy, verificar si es después de las 12:00 pm
                limite_pm = hora_actual_rd.replace(hour=12, minute=0, second=0, microsecond=0)
                
                if hora_actual_rd >= limite_pm:
                    flash("❌ No se pueden registrar citas para hoy después de las 12:00 PM (hora República Dominicana). Por favor, seleccione otra fecha.", "error")
                    return redirect(url_for("registrar_cita"))
                    
        except pytz.exceptions.UnknownTimeZoneError:
            # Si hay error con la zona horaria, usar UTC-4 como fallback
            print("⚠️ Error con zona horaria, usando UTC-4 como fallback")
            hora_actual = datetime.utcnow() - timedelta(hours=4)
            hoy = hora_actual.date()
            
            if fecha_obj == hoy:
                if hora_actual.hour >= 12:
                    flash("❌ No se pueden registrar citas para hoy después de las 12:00 PM. Por favor, seleccione otra fecha.", "error")
                    return redirect(url_for("registrar_cita"))
        except Exception as e:
            print(f"⚠️ Error en validación de hora: {e}")
            # Continuar sin la restricción si hay error

        if fecha_str in fechas_bloqueadas_manualmente:
            flash("❌ La fecha seleccionada no está disponible. Por favor, elija otra.", "error")
            return redirect(url_for("registrar_cita"))

        if fecha_str in dias_llenos:
            flash("❌ El cupo para la fecha seleccionada está lleno. Por favor, elija otra.", "error")
            return redirect(url_for("registrar_cita"))

        # --- Recolección de datos del formulario ---
        cedula_raw = request.form.get("cedula", "").strip()
        nombre = request.form["nombre"].strip()
        telefono = request.form["telefono"].strip()
        motivo = request.form["motivo"].strip()
        nombre_seguro_medico = request.form["nombre_seguro_medico"].strip()
        numero_seguro_medico = request.form["numero_seguro_medico"].strip()

         # --- VALIDAR FORMATO DE CÉDULA ---
        if cedula_raw:
            if not re.match(r"^\d{3}-\d{7}-\d{1}$", cedula_raw):
              flash("❌ El formato de la cédula no es válido. Use 000-0000000-0", "error")
              return redirect(url_for("registrar_cita"))
              

        # --- Validación de datos del paciente ---
        if not nombre:
            flash("❌ El nombre del paciente es obligatorio.", "error")
            return redirect(url_for("registrar_cita"))
            
        if not telefono:
            flash("❌ El teléfono del paciente es obligatorio.", "error")
            return redirect(url_for("registrar_cita"))
            
        if not fecha_str:
            flash("❌ La fecha de la cita es obligatoria.", "error")
            return redirect(url_for("registrar_cita"))
            
        # Validar formato del teléfono (debe tener al menos 10 dígitos)
        telefono_limpio = re.sub(r'[^0-9]', '', telefono)
        if len(telefono_limpio) < 10:
            flash("❌ El número de teléfono debe tener al menos 10 dígitos.", "error")
            return redirect(url_for("registrar_cita"))
        
        # --- Guardar/actualizar paciente ---
        try:
            paciente_data = {
                "nombre_completo": nombre,
                "telefono": telefono,
                "nombre_seguro_medico": nombre_seguro_medico,
                "numero_seguro_medico": numero_seguro_medico
            }
            # Si hay cédula, la agregamos al diccionario
            if cedula_raw:
                paciente_data["cedula"] = cedula_raw
                # Usar upsert cuando hay cédula
                supabase.table("pacientes").upsert(paciente_data, on_conflict="cedula").execute()
            else:
                # Buscar si ya existe un paciente con el mismo nombre y teléfono
                existing_patient = supabase.table("pacientes").select("*").eq("nombre_completo", nombre).eq("telefono", telefono).execute()
                if existing_patient.data:
                    # Actualizar el paciente existente
                    supabase.table("pacientes").update(paciente_data).eq("nombre_completo", nombre).eq("telefono", telefono).execute()
                else:
                    # Crear nuevo paciente
                    supabase.table("pacientes").insert(paciente_data).execute()
        except Exception as e:
            print(f"⚠️ No se pudo guardar/actualizar paciente: {e}")
            # Si hay un error de permisos, continuar con el registro de la cita
            if isinstance(e, APIError) and e.json()['code'] == '42501':
                print("Continuando con el registro de la cita a pesar del error de permisos...")
        
        # --- NUEVO: VALIDACIÓN DE CITA DUPLICADA ---
        try:
            # Construimos la consulta base para la fecha
            query = supabase.table("citas").select("id", count='exact').eq("fecha", fecha_str)

            # Añadimos el identificador del paciente a la consulta
            if cedula_raw:
                # Si hay cédula, es el mejor identificador
                query = query.eq("cedula", cedula_raw)
            else:
                # Si no, usamos la combinación de nombre y teléfono
                query = query.eq("nombre", nombre).eq("telefono", telefono)
            
            # Ejecutamos la consulta
            existing_cita_result = query.execute()

            # Si el contador es mayor que 0, ya existe una cita
            if existing_cita_result.count > 0:
                flash("❌ Ya tienes una cita registrada para esta fecha. Por favor, elige otra.", "error")
                return redirect(url_for("registrar_cita"))

        except Exception as e:
            print(f"Error al verificar cita duplicada: {e}")
            flash("❌ Ocurrió un error al verificar sus citas existentes. Intente de nuevo.", "error")
            return redirect(url_for("registrar_cita"))
        # --- FIN DE LA VALIDACIÓN NUEVA ---

        # --- Registrar cita ---
        data_cita = {
            "nombre": nombre,
            "telefono": telefono,
            "email": "",  # opcional
            "fecha": fecha_str,
            "motivo": motivo,
            "tanda": "",
            "numero_seguro_medico": numero_seguro_medico,
            "nombre_seguro_medico": nombre_seguro_medico,
            "tipo_seguro_medico": "",
            "cedula": cedula_raw if cedula_raw else None
        }

        try:
            supabase.table("citas").insert(data_cita).execute()
            flash("✅ Cita registrada correctamente", "success")

            # --- Notificaciones ---
            mensaje = {
                "Nombre del paciente": nombre,
                "Teléfono": telefono,
                "Fecha": fecha_str,
                "Motivo": motivo,
                "Número de Seguro Médico": numero_seguro_medico,
                "Nombre del Seguro Médico": nombre_seguro_medico
            }
            #enviar mensaje al paciente
            send_whatsapp_reminder(telefono, nombre, fecha_str)
            #enviar mensaje a la secretaria
            send_whatsapp_reminder_secretaria(nombre, telefono, fecha_str, motivo, numero_seguro_medico, nombre_seguro_medico)
            #enviar mensaje a telegram
            send_telegram_message("📅 Nueva cita registrada:\n" + "\n".join([f"{k}: {v}" for k, v in mensaje.items()]))

        except Exception as e:
            flash(f"❌ Error al registrar la cita: {e}", "error")
            print(f"Error en Supabase: {e}")
            return render_template("form.html",
                                   fechas_bloqueadas=fechas_no_disponibles,
                                   dias_llenos=list(dias_llenos),
                                   configuracion=config,
                                   form_data=request.form)

        return redirect(url_for("registrar_cita"))

    # --- Si es GET, renderizamos el formulario ---
    return render_template("form.html",
                           fechas_bloqueadas=fechas_no_disponibles,
                           dias_llenos=list(dias_llenos),
                           configuracion=config)

# @app.route("/cita", methods=["GET", "POST"])
# @public_route
# def registrar_cita():
#     config = get_configuracion()
    
#     # --- OBTENER FECHAS NO DISPONIBLES (BLOQUEADAS + LLENAS) ---
#     try:
#         fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
#         fechas_bloqueadas_manualmente = {f["fecha"] for f in fechas_bloqueadas_data}
#     except Exception as e:
#         # ... (código de manejo de error)
#         fechas_bloqueadas_manualmente = set()

#     dias_llenos = set(get_dias_llenos(config))
#     # Combinamos ambas listas para pasarlas al frontend
#     fechas_no_disponibles = list(fechas_bloqueadas_manualmente.union(dias_llenos))

#     if request.method == "POST":
#         fecha_str = request.form["fecha"]
#         fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()

#         # VALIDACIÓN 1: Fin de semana
#         if config.get('bloquear_sabados') == 'true' and fecha_obj.weekday() == 5:
#             flash("❌ No se pueden agendar citas los sábados.", "error")
#             return render_template("form.html", 
#                                 fechas_bloqueadas=fechas_bloqueadas,
#                                 dias_llenos=dias_llenos,
#                                 configuracion=config,
#                                 form_data=request.form)
#         if config.get('bloquear_domingos') == 'true' and fecha_obj.weekday() == 6:
#             flash("❌ No se pueden agendar citas los domingos.", "error")
#             return render_template("form.html", 
#                                 fechas_bloqueadas=fechas_bloqueadas,
#                                 dias_llenos=dias_llenos,
#                                 configuracion=config,
#                                 form_data=request.form)
            
#         # VALIDACIÓN 2: Fecha bloqueada manualmente
#         if fecha_str in fechas_bloqueadas_manualmente:
#             flash("❌ La fecha seleccionada no está disponible. Por favor, elija otra.", "error")
#             return render_template("form.html", 
#                                 fechas_bloqueadas=fechas_bloqueadas,
#                                 dias_llenos=dias_llenos,
#                                 configuracion=config,
#                                 form_data=request.form)

#         # VALIDACIÓN 3: Límite de pacientes por día
#         if fecha_str in dias_llenos:
#              flash("❌ El cupo para la fecha seleccionada está lleno. Por favor, elija otra.", "error")
#              return render_template("form.html", 
#                                 fechas_bloqueadas=fechas_bloqueadas,
#                                 dias_llenos=dias_llenos,
#                                 configuracion=config,
#                                 form_data=request.form)
#     # Traer fechas bloqueadas
#     try:
#         fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
#         # Extraer solo las fechas en formato 'YYYY-MM-DD'
#         fechas_bloqueadas = [f["fecha"] for f in fechas_bloqueadas_data]
#     except Exception as e:
#         print(f"Error al obtener fechas bloqueadas: {e}")
#         fechas_bloqueadas = [] # Si hay un error, usa una lista vacía para no romper la página

#     config = get_configuracion() # <-- Obtener configuración
#     try:
#         fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
#         fechas_bloqueadas = [f["fecha"] for f in fechas_bloqueadas_data]
#     except Exception as e:
#         print(f"Error al obtener fechas bloqueadas: {e}")
#         fechas_bloqueadas = []

#     if request.method == "POST":
#         fecha_str = request.form["fecha"]
#         fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d')
        
#         # --- VALIDACIÓN DE FINES DE SEMANA ---
#         # weekday(): Lunes=0, Martes=1, ..., Sábado=5, Domingo=6
#         if config.get('bloquear_sabados') == 'true' and fecha_obj.weekday() == 5:
#             flash("❌ No se pueden agendar citas los sábados.", "error")
#             return redirect(url_for("registrar_cita"))
#         if config.get('bloquear_domingos') == 'true' and fecha_obj.weekday() == 6:
#             flash("❌ No se pueden agendar citas los domingos.", "error")
#             return redirect(url_for("registrar_cita"))
            
#         if fecha_str in fechas_bloqueadas:
#             flash("❌ La fecha seleccionada no está disponible. Por favor, elija otra.", "error")
#             return redirect(url_for("registrar_cita"))

#     if request.method == "POST":
#         fecha = request.form["fecha"]
#         # La validación en el backend sigue siendo crucial como medida de seguridad
#         if fecha in fechas_bloqueadas:
#             flash("❌ La fecha seleccionada no está disponible. Por favor, elija otra.", "error")
#             return redirect(url_for("registrar_cita"))
        
#         # ... (resto del código POST sin cambios)
#         nombre = request.form["nombre"]
#         telefono = request.form["telefono"]
#         email = "" 
#         motivo = request.form["motivo"]
#         tanda = ""
#         numero_seguro_medico = request.form["numero_seguro_medico"]
#         nombre_seguro_medico = request.form["nombre_seguro_medico"]
#         tipo_seguro_medico = ""

#         data = {
#             "nombre": nombre,
#             "telefono": telefono,
#             "email": "",
#             "fecha": fecha,
#             "motivo": motivo,
#             "tanda": tanda,
#             "numero_seguro_medico": numero_seguro_medico,
#             "nombre_seguro_medico": nombre_seguro_medico,
#             "tipo_seguro_medico": tipo_seguro_medico
#         }
        
#         try:
#             supabase.table("citas").insert(data).execute()
#             flash("✅ Cita registrada correctamente", "success")
#             #enviar mensaje a telegram
#             mensaje = {
#                 "Nombre del paciente": nombre,
#                 "Telefono": telefono,
#                 "Fecha": fecha,
#                 "Motivo": motivo,
#                 "Numero de Seguro Médico": numero_seguro_medico,
#                 "Nombre del seguro médico": nombre_seguro_medico
#             }
#             #enviar mensaje a whatsapp
#             send_whatsapp_reminder(telefono, nombre, fecha)
#             #enviar mensaje de telegram
#             send_telegram_message("Nueva cita registrada:\n" + "\n".join([f"{k}: {v}" for k, v in mensaje.items()]))

#         except Exception as e:
#             flash(f"❌ Error al registrar la cita: {e}", "error")
#             print(f"Error en Supabase: {e}")
#             # En caso de error, renderizamos el formulario nuevamente con los datos
#             return render_template("form.html", 
#                                 fechas_bloqueadas=fechas_bloqueadas, 
#                                 dias_llenos=dias_llenos,
#                                 configuracion=config,
#                                 form_data=request.form)  # Mantenemos los datos del formulario
            
#         # Solo redirigimos si la cita se registró correctamente
#         #flash("✅ Cita registrada correctamente", "success")
#         return redirect(url_for("registrar_cita"))
    
#     # Si es GET, renderiza la plantilla y pasa la lista de fechas y la configuración
#     config = get_configuracion()
#     dias_llenos = get_dias_llenos()  # Obtiene los días que están llenos usando la función existente
#     return render_template("form.html", fechas_bloqueadas=fechas_bloqueadas, dias_llenos=dias_llenos, configuracion=config)

# 👇 Formulario para bloquear fechas (VERSIÓN CORREGIDA)
@app.route("/bloquear", methods=["GET", "POST"])
def bloquear_fecha():
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder al panel", "error")
        return redirect(url_for("login"))
    
    if request.method == "POST":
        fecha = request.form["fecha"]
        motivo = request.form.get("motivo", "") # Usar .get() para campos opcionales

        try:
            # 1. VERIFICAR si la fecha ya existe
            existing_block = supabase.table("fechas_bloqueadas").select("fecha").eq("fecha", fecha).execute()

            # 2. SI YA EXISTE, mostrar un error y no insertar
            if existing_block.data:
                flash(f"❌ La fecha {fecha} ya se encuentra bloqueada.", "error")
                return redirect(url_for("bloquear_fecha"))

            # 3. SI NO EXISTE, proceder con la inserción
            supabase.table("fechas_bloqueadas").insert({
                "fecha": fecha,
                "motivo": motivo
            }).execute()

            flash(f"✅ Fecha {fecha} bloqueada correctamente", "success")

        except Exception as e:
            # Capturar cualquier otro error inesperado
            flash(f"❌ Ocurrió un error inesperado: {e}", "error")
            print(f"Error al bloquear fecha: {e}")

        return redirect(url_for("bloquear_fecha"))

    return render_template("bloquear.html")

# 👇 Formulario para bloquear fechas (VERSIÓN CORREGIDA)
@app.route("/secretaria/bloquear", methods=["GET", "POST"])
def secretaria_bloquear_fecha():
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder al panel", "error")
        return redirect(url_for("login"))
    
    if request.method == "POST":
        fecha = request.form["fecha"]
        motivo = request.form.get("motivo", "") # Usar .get() para campos opcionales

        try:
            # 1. VERIFICAR si la fecha ya existe
            existing_block = supabase.table("fechas_bloqueadas").select("fecha").eq("fecha", fecha).execute()

            # 2. SI YA EXISTE, mostrar un error y no insertar
            if existing_block.data:
                flash(f"❌ La fecha {fecha} ya se encuentra bloqueada.", "error")
                return redirect(url_for("bloquear_fecha"))

            # 3. SI NO EXISTE, proceder con la inserción
            supabase.table("fechas_bloqueadas").insert({
                "fecha": fecha,
                "motivo": motivo
            }).execute()

            flash(f"✅ Fecha {fecha} bloqueada correctamente", "success")

        except Exception as e:
            # Capturar cualquier otro error inesperado
            flash(f"❌ Ocurrió un error inesperado: {e}", "error")
            print(f"Error al bloquear fecha: {e}")

        return redirect(url_for("secretaria_bloquear_fecha"))

    return render_template("secretaria_bloquear.html")


@app.route("/login", methods=["GET", "POST"])
@public_route
def login():
    if "usuario" in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin'))
        else:
            return redirect(url_for('secretaria_dashboard'))
        
    if request.method == "POST":
        username = request.form["usuario"]
        password = request.form["clave"]

        try:
            any_user = supabase.table("usuarios").select("id").execute().data
            if not any_user:
                flash("❌ No hay usuarios registrados. Crea un administrador primero.", "error")
                return redirect(url_for("crear_admin_inicial"))

            response = supabase.table("usuarios").select("*").eq("username", username).execute()
            users = response.data

            if not users:
                flash("❌ Usuario o contraseña incorrectos.", "error")
                return redirect(url_for("login"))

            user_data = users[0]
            
            # La verificación de contraseña y sesión de Flask es todo lo que necesitamos
            if check_password_hash(user_data['password_hash'], password):
                session["usuario"] = user_data['username']
                session["role"] = user_data['role'] # <--- Cambiado de 'rol' a 'role' para consistencia
                
                flash(f"✅ ¡Bienvenido de nuevo, {user_data['username']}!", "success")

                if user_data['role'] == 'admin':
                    return redirect(url_for("admin"))
                else: 
                    return redirect(url_for("secretaria_dashboard"))
            else:
                flash("❌ Usuario o contraseña incorrectos.", "error")
                return redirect(url_for("login"))
                
        except Exception as e:
            print(f"Error al intentar iniciar sesión: {e}")
            flash("❌ Ocurrió un error al intentar iniciar sesión. Por favor, inténtalo de nuevo.", "error")
            return redirect(url_for("login"))

    return render_template("login.html")

# Logout
@app.route("/logout")
def logout():
    session.pop("usuario", None)
    flash("👋 Sesión cerrada correctamente", "success")
    return redirect(url_for("login"))

@app.route("/admin")
@role_required('admin')  # Solo administradores pueden acceder aquí
def admin():
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder al panel", "error")
        return redirect(url_for("login"))

    filtro_fecha = request.args.get("fecha")
    
    # Prepara la consulta base, AHORA ORDENANDO POR LA NUEVA COLUMNA 'orden'
    query = supabase.table("citas").select("*").order("orden", desc=False) # desc=False es ascendente (0, 1, 2...)

    if filtro_fecha is None:
        filtro_fecha = date.today().strftime('%Y-%m-%d')
        query = query.eq("fecha", filtro_fecha)
    elif filtro_fecha:
        query = query.eq("fecha", filtro_fecha)
    
    citas = query.execute().data
    bloqueadas = supabase.table("fechas_bloqueadas").select("*").order("fecha", desc=True).execute().data

    return render_template("admin.html", citas=citas, bloqueadas=bloqueadas, filtro_fecha=filtro_fecha)

@app.route('/admin/actualizar_orden', methods=['POST'])
def actualizar_orden():
    if "usuario" not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401

    try:
        data = request.get_json()
        ordered_ids = data.get('order')

        if not ordered_ids:
            return jsonify({'success': False, 'error': 'No se proporcionó orden'}), 400

        # Prepara los datos para la actualización masiva (upsert)
        updates = []
        for index, cita_id in enumerate(ordered_ids):
            updates.append({
                'id': int(cita_id), 
                'orden': index  # El nuevo orden es el índice en la lista
            })

        # Ejecuta la actualización en Supabase de forma individual para cada cita
        for update in updates:
            supabase.table('citas').update({'orden': update['orden']}).eq('id', update['id']).execute()
        
        return jsonify({'success': True})

    except Exception as e:
        print(f"Error al actualizar orden: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# NUEVA RUTA para mostrar el formulario y procesar el cambio de fecha
@app.route("/admin/mover_cita/<int:id>", methods=["GET", "POST"])
def mover_cita(id):
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder", "error")
        return redirect(url_for("login"))
        
    config = get_configuracion() # <-- Obtener configuración
    fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
    fechas_bloqueadas = [f["fecha"] for f in fechas_bloqueadas_data]

    try:
        fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
        fechas_bloqueadas_manualmente = {f["fecha"] for f in fechas_bloqueadas_data}
    except:
        fechas_bloqueadas_manualmente = set()

    dias_llenos = set(get_dias_llenos())
    fechas_no_disponibles = list(fechas_bloqueadas_manualmente.union(dias_llenos))

    if request.method == "POST":
        nueva_fecha_str = request.form["nueva_fecha"]
        nueva_fecha_obj = datetime.strptime(nueva_fecha_str, '%Y-%m-%d')

        if nueva_fecha_str in fechas_no_disponibles:
            flash(f"❌ No se puede mover la cita al {nueva_fecha_str} porque la fecha está llena o bloqueada.", "error")
            return redirect(url_for("mover_cita", id=id))

        # --- VALIDACIÓN DE FINES DE SEMANA (también aquí) ---
        if config.get('bloquear_sabados') == 'true' and nueva_fecha_obj.weekday() == 5:
            flash("❌ No se pueden mover citas a los sábados.", "error")
            return redirect(url_for("mover_cita", id=id))
        if config.get('bloquear_domingos') == 'true' and nueva_fecha_obj.weekday() == 6:
            flash("❌ No se pueden mover citas a los domingos.", "error")
            return redirect(url_for("mover_cita", id=id))
            
        if nueva_fecha_str in fechas_bloqueadas:
            flash(f"❌ No se puede mover la cita al {nueva_fecha_str} porque es una fecha bloqueada.", "error")
            return redirect(url_for("mover_cita", id=id))

    # Traer fechas bloqueadas para la validación
    fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
    fechas_bloqueadas = [f["fecha"] for f in fechas_bloqueadas_data]

    if request.method == "POST":
        nueva_fecha = request.form["nueva_fecha"]

        # Validar en backend que la nueva fecha no esté bloqueada
        if nueva_fecha in fechas_bloqueadas:
            flash(f"❌ No se puede mover la cita al {nueva_fecha} porque es una fecha bloqueada.", "error")
            return redirect(url_for("mover_cita", id=id))
        
        # Verificar si la cita tiene pagos registrados
        try:
            pagos = supabase.table("pagos").select("*").eq("cita_id", id).execute().data
            if pagos:
                flash("❌ No se puede mover la cita del paciente ya que tiene un pago registrado en el sistema.", "error")
                return redirect(url_for("admin"))
        except Exception as e:
            flash(f"❌ Error al verificar los pagos: {e}", "error")
            return redirect(url_for("admin"))

        # Actualizar la fecha en la base de datos
        try:
            # Obtener los datos de la cita antes de actualizarla
            cita = supabase.table("citas").select("*").eq("id", id).single().execute().data
            fecha_anterior = cita.get('fecha', 'desconocida')

            if not cita:
                flash("❌ Cita no encontrada.", "error")
                return redirect(url_for("admin"))
                
            # Actualizar la fecha
            supabase.table("citas").update({"fecha": nueva_fecha}).eq("id", id).execute()
            flash("✅ Cita movida correctamente a la nueva fecha.", "success")

            # --- CONSTRUIR Y ENVIAR NOTIFICACIÓN DETALLADA POR TELEGRAM ---
            # Usamos .get() para evitar errores si algún campo no existe o es nulo
            cita = supabase.table("citas").select("*").eq("id", id).single().execute().data

            paciente = cita.get('nombre', 'No especificado')
            motivo = cita.get('motivo', 'No especificado')
            #seguro = cita.get('nombre_seguro_medico', 'No aplica')
            #num_seguro = cita.get('numero_seguro_medico', '')
            fecha_nueva = cita.get('fecha', 'desconocida')

            mensaje_telegram = (
                f"🔄 *Cita Movida Exitosamente (Secretaria)*\n\n"
                f"Se ha cambiado la fecha de la siguiente cita:\n\n"
                f"👤 *Paciente:* {paciente}\n"
                f"🗓️ *Fecha Anterior:* {fecha_anterior}\n"
                f"➡️ *Nueva Fecha:* {fecha_nueva}\n\n"
                f"📋 *Detalles Adicionales:*\n"
                f"   - *Motivo:* {motivo}\n"
            )

            #print(mensaje_telegram)
            
            send_telegram_message(mensaje_telegram)
            # Redirigir al panel de administración
            return redirect(url_for("admin"))
        except Exception as e:
            flash(f"❌ Error al mover la cita: {e}", "error")
            return redirect(url_for("mover_cita", id=id))

    # Si es GET, mostrar el formulario con los datos de la cita
    try:
        cita = supabase.table("citas").select("*").eq("id", id).single().execute().data
        if not cita:
            flash("❌ Cita no encontrada.", "error")
            return redirect(url_for("admin"))
    except Exception as e:
        flash(f"❌ Error al buscar la cita: {e}", "error")
        return redirect(url_for("admin"))

    return render_template("mover_cita.html", cita=cita, fechas_bloqueadas=fechas_bloqueadas)

# NUEVA RUTA para mostrar el formulario y procesar el cambio de fecha
@app.route("/secretaria/mover_cita/<int:id>", methods=["GET", "POST"])
def secretaria_mover_cita(id):
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder", "error")
        return redirect(url_for("login"))
    
    config = get_configuracion() # <-- Obtener configuración
    fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
    fechas_bloqueadas = [f["fecha"] for f in fechas_bloqueadas_data]

    try:
        fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
        fechas_bloqueadas_manualmente = {f["fecha"] for f in fechas_bloqueadas_data}
    except:
        fechas_bloqueadas_manualmente = set()

    dias_llenos = set(get_dias_llenos())
    fechas_no_disponibles = list(fechas_bloqueadas_manualmente.union(dias_llenos))

    if request.method == "POST":
        nueva_fecha_str = request.form["nueva_fecha"]
        nueva_fecha_obj = datetime.strptime(nueva_fecha_str, '%Y-%m-%d')

        if nueva_fecha_str in fechas_no_disponibles:
            flash(f"❌ No se puede mover la cita al {nueva_fecha_str} porque la fecha está llena o bloqueada.", "error")
            return redirect(url_for("secretaria_mover_cita", id=id))

        # --- VALIDACIÓN DE FINES DE SEMANA (también aquí) ---
        if config.get('bloquear_sabados') == 'true' and nueva_fecha_obj.weekday() == 5:
            flash("❌ No se pueden mover citas a los sábados.", "error")
            return redirect(url_for("secretaria_mover_cita", id=id))
        if config.get('bloquear_domingos') == 'true' and nueva_fecha_obj.weekday() == 6:
            flash("❌ No se pueden mover citas a los domingos.", "error")
            return redirect(url_for("secretaria_mover_cita", id=id))
            
        if nueva_fecha_str in fechas_bloqueadas:
            flash(f"❌ No se puede mover la cita al {nueva_fecha_str} porque es una fecha bloqueada.", "error")
            return redirect(url_for("secretaria_mover_cita", id=id))
        
        # Verificar si la cita tiene pagos registrados
        try:
            pagos = supabase.table("pagos").select("*").eq("cita_id", id).execute().data
            if pagos:
                flash("❌ No se puede mover la cita del paciente ya que tiene un pago registrado en el sistema.", "error")
                return redirect(url_for("secretaria_dashboard"))
        except Exception as e:
            flash(f"❌ Error al verificar los pagos: {e}", "error")
            return redirect(url_for("secretaria_dashboard"))

    # Traer fechas bloqueadas para la validación
    fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
    fechas_bloqueadas = [f["fecha"] for f in fechas_bloqueadas_data]

    if request.method == "POST":
        nueva_fecha = request.form["nueva_fecha"]

        # Validar en backend que la nueva fecha no esté bloqueada
        if nueva_fecha in fechas_bloqueadas:
            flash(f"❌ No se puede mover la cita al {nueva_fecha} porque es una fecha bloqueada.", "error")
            return redirect(url_for("secretaria_mover_cita", id=id))

        # Actualizar la fecha en la base de datos
        try:
            # Obtener los datos de la cita antes de actualizarla
            cita = supabase.table("citas").select("*").eq("id", id).single().execute().data
            fecha_anterior = cita.get('fecha', 'desconocida')

            if not cita:
                flash("❌ Cita no encontrada.", "error")
                return redirect(url_for("secretaria_dashboard"))
                
            # Actualizar la fecha
            supabase.table("citas").update({"fecha": nueva_fecha}).eq("id", id).execute()
            flash("✅ Cita movida correctamente a la nueva fecha.", "success")

            # --- CONSTRUIR Y ENVIAR NOTIFICACIÓN DETALLADA POR TELEGRAM ---
            # Usamos .get() para evitar errores si algún campo no existe o es nulo
            cita = supabase.table("citas").select("*").eq("id", id).single().execute().data

            paciente = cita.get('nombre', 'No especificado')
            motivo = cita.get('motivo', 'No especificado')
            #seguro = cita.get('nombre_seguro_medico', 'No aplica')
            #num_seguro = cita.get('numero_seguro_medico', '')
            fecha_nueva = cita.get('fecha', 'desconocida')

            mensaje_telegram = (
                f"🔄 *Cita Movida Exitosamente (Secretaria)*\n\n"
                f"Se ha cambiado la fecha de la siguiente cita:\n\n"
                f"👤 *Paciente:* {paciente}\n"
                f"🗓️ *Fecha Anterior:* {fecha_anterior}\n"
                f"➡️ *Nueva Fecha:* {fecha_nueva}\n\n"
                f"📋 *Detalles Adicionales:*\n"
                f"   - *Motivo:* {motivo}\n"
            )
            #print(mensaje_telegram)
            #enviar mensaje a telegram
            send_telegram_message(mensaje_telegram)
            # Redirigir al panel de secretaria
            return redirect(url_for("secretaria_dashboard"))
        except Exception as e:
            flash(f"❌ Error al mover la cita: {e}", "error")
            return redirect(url_for("secretaria_mover_cita", id=id))

    # Si es GET, mostrar el formulario con los datos de la cita
    try:
        cita = supabase.table("citas").select("*").eq("id", id).single().execute().data
        if not cita:
            flash("❌ Cita no encontrada.", "error")
            return redirect(url_for("secretaria_dashboard"))
    except Exception as e:
        flash(f"❌ Error al buscar la cita: {e}", "error")
        return redirect(url_for("secretaria_dashboard"))

    return render_template("secretaria_mover_cita.html", cita=cita, fechas_bloqueadas=fechas_bloqueadas)

# RUTA ELIMINADA: ya no la necesitamos
# @app.route("/admin/eliminar_cita/<int:id>", methods=["POST"])

# Desbloquear fecha (lógica sin cambios, pero la llamaremos desde el nuevo panel)
@app.route("/admin/desbloquear/<int:id>", methods=["POST"])
def desbloquear(id):
    if "usuario" not in session:
        return redirect(url_for("login"))
    supabase.table("fechas_bloqueadas").delete().eq("id", id).execute()
    flash("✅ Fecha desbloqueada correctamente", "success")
    return redirect(url_for("admin"))

# Desbloquear fecha (lógica sin cambios, pero la llamaremos desde el nuevo panel)
@app.route("/secretaria/desbloquear/<int:id>", methods=["POST"])
def secretaria_desbloquear(id):
    if "usuario" not in session:
        return redirect(url_for("login"))
    supabase.table("fechas_bloqueadas").delete().eq("id", id).execute()
    flash("✅ Fecha desbloqueada correctamente", "success")
    return redirect(url_for("secretaria_dashboard"))


# 1. RUTA DE STREAMING: La tablet se conecta aquí para escuchar
@app.route('/stream')
@public_route
def stream():
    def event_stream():
        while True:
            try:
                nombre_paciente = announcement_queue.get(timeout=5)
                yield f"data: {nombre_paciente}\n\n"
            except Empty:
                yield ": keep-alive\n\n"
    
    return Response(event_stream(), mimetype='text/event-stream')


# NUEVA RUTA: La página del doctor enviará el nombre del paciente aquí
@app.route('/admin/anunciar_llamada', methods=['POST'])
def anunciar_llamada():
    if "usuario" not in session:
        return jsonify({"error": "No autorizado"}), 401
    
    data = request.get_json()
    nombre = data.get('nombre')

    if not nombre:
        return jsonify({"error": "Nombre del paciente no proporcionado"}), 400
    
    # Añadimos el nombre del paciente a la cola
    announcement_queue.put(nombre)
    
    print(f"Anuncio para '{nombre}' puesto en la cola.") # Para debugging en la consola de Flask
    return jsonify({"success": True, "message": f"Anuncio para {nombre} enviado."})

# NUEVA RUTA: Para renderizar la página de la sala de espera
@app.route('/sala_espera')
@public_route
def sala_espera():
    # No requiere login, ya que es una pantalla pública
    return render_template('sala_espera.html')

@app.route("/admin/llamar")
def llamar_paciente():
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder", "error")
        return redirect(url_for("login"))

    # Obtener la fecha del filtro. Si no hay, usar la de hoy por defecto.
    filtro_fecha = request.args.get("fecha")
    if not filtro_fecha:
        filtro_fecha = date.today().strftime('%Y-%m-%d')
    
    citas = []
    try:
        # Consultar solo los campos necesarios (nombre) para la fecha filtrada
        # Ordenamos por nombre para tener una lista alfabética
        response = supabase.table("citas").select("id, nombre") \
                                          .eq("fecha", filtro_fecha) \
                                          .order("orden", desc=False) \
                                          .execute()
        citas = response.data
    except Exception as e:
        flash(f"❌ Error al cargar la lista de pacientes: {e}", "error")
        print(f"Error cargando pacientes: {e}")

    # Esta línea renderiza el formulario que crearemos en el siguiente paso
    return render_template("llamar_paciente.html", citas=citas, filtro_fecha=filtro_fecha)

@app.route('/admin/marcar_llamado/<int:cita_id>', methods=['POST'])
def marcar_llamado(cita_id):
    if "usuario" not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    
    try:
        supabase.table('citas').update({'fue_llamado': True}).eq('id', cita_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error al marcar como llamado: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# 2. RUTA DE LA SALA UNIFICADA: Carga la página para la doctora y la tablet
@app.route("/sala")
def sala_unificada():
    es_doctor = "usuario" in session
    filtro_fecha = request.args.get("fecha", date.today().strftime('%Y-%m-%d'))
    
    citas = []
    if es_doctor:
        try:
            response = supabase.table("citas").select("id, nombre, fue_llamado") \
                                              .eq("fecha", filtro_fecha) \
                                              .order("orden", desc=False) \
                                              .execute()
            citas = response.data
        except Exception as e:
            flash(f"❌ Error al cargar la lista de pacientes: {e}", "error")
    
    return render_template(
        "sala_unificada.html", 
        citas=citas, 
        filtro_fecha=filtro_fecha, 
        es_doctor=es_doctor
    )

# 👇 NUEVA RUTA UNIFICADA QUE REEMPLAZA A LAS DOS ANTERIORES 👇
@app.route("/sala_paciente")
def sala_paciente():
    # Determinamos si el usuario es la doctora (si ha iniciado sesión)
    es_doctor = "usuario" in session

    # Por defecto, la fecha es hoy.
    filtro_fecha = request.args.get("fecha", date.today().strftime('%Y-%m-%d'))
    
    citas = []
    # Solo buscamos la lista de pacientes si es la doctora quien visita la página
    if es_doctor:
        try:
            response = supabase.table("citas").select("id, nombre") \
                                              .eq("fecha", filtro_fecha) \
                                              .order("orden", desc=False) \
                                              .execute()
            citas = response.data
        except Exception as e:
            flash(f"❌ Error al cargar la lista de pacientes: {e}", "error")
            print(f"Error cargando pacientes: {e}")

    # Renderizamos la nueva plantilla unificada, pasándole toda la información
    return render_template(
        "sala_paciente.html", 
        citas=citas, 
        filtro_fecha=filtro_fecha, 
        es_doctor=es_doctor
    )

# === RUTAS DE GESTIÓN DE USUARIOS ===
@app.route("/admin/usuarios", methods=["GET", "POST"])
@role_required('admin')
def gestion_usuarios():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        role = request.form["role"]
        
        # Validar que el usuario no exista
        try:
            exists = supabase.table("usuarios").select("id").eq("username", username).execute().data
            if exists:
                flash("❌ El nombre de usuario ya existe", "error")
                return redirect(url_for("gestion_usuarios"))
        except Exception as e:
            flash(f"❌ Error al verificar usuario: {e}", "error")
            return redirect(url_for("gestion_usuarios"))
        
        # Crear nuevo usuario
        try:
            password_hash = generate_password_hash(password)
            data = {
                "username": username,
                "password_hash": password_hash,
                "role": role
            }
            supabase.table("usuarios").insert(data).execute()
            flash("✅ Usuario creado correctamente", "success")
        except Exception as e:
            flash(f"❌ Error al crear usuario: {e}", "error")
        
        return redirect(url_for("gestion_usuarios"))
    
    # GET: mostrar lista de usuarios
    try:
        usuarios = supabase.table("usuarios").select("*").execute().data
    except Exception as e:
        usuarios = []
        flash(f"❌ Error al cargar usuarios: {e}", "error")
    
    return render_template("usuarios.html", usuarios=usuarios)

@app.route("/admin/usuarios/eliminar/<int:user_id>", methods=["POST"])
@role_required('admin')
def eliminar_usuario(user_id):
    try:
        # No permitir eliminar el último administrador
        admins = supabase.table("usuarios").select("id").eq("role", "admin").execute().data
        if len(admins) <= 1:
            user = supabase.table("usuarios").select("role").eq("id", user_id).single().execute().data
            if user and user.get("role") == "admin":
                flash("❌ No se puede eliminar el último administrador", "error")
                return redirect(url_for("gestion_usuarios"))
        
        supabase.table("usuarios").delete().eq("id", user_id).execute()
        flash("✅ Usuario eliminado correctamente", "success")
    except Exception as e:
        flash(f"❌ Error al eliminar usuario: {e}", "error")
    
    return redirect(url_for("gestion_usuarios"))

@app.route("/crear_admin_inicial", methods=["GET", "POST"])
@public_route
def crear_admin_inicial():
    # Limpiar cualquier sesión existente
    session.clear()
    
    # Verificar si ya existe algún usuario
    try:
        exists = supabase.table("usuarios").select("id").execute().data
        if exists:
            flash("❌ Ya existen usuarios en el sistema", "error")
            return redirect(url_for("login"))
    except Exception as e:
        flash(f"❌ Error al verificar usuarios: {e}", "error")
        return redirect(url_for("login"))
    
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        
        try:
            password_hash = generate_password_hash(password)
            data = {
                "username": username,
                "password_hash": password_hash,
                "role": "admin"  # El primer usuario siempre es admin
            }
            
            # Crear el usuario administrador
            response = supabase.table("usuarios").insert(data).execute()
            
            if response.data:
                flash("✅ Administrador inicial creado correctamente. Por favor inicia sesión.", "success")
                return redirect(url_for("login"))
            else:
                flash("❌ Error al crear el administrador: No se recibió confirmación", "error")
                return redirect(url_for("crear_admin_inicial"))
                
        except Exception as e:
            flash(f"❌ Error al crear administrador: {e}", "error")
            return redirect(url_for("crear_admin_inicial"))
    
    return render_template("crear_admin.html")

# 3. RUTA DE ACCIÓN: La doctora envía aquí la orden de llamar
@app.route('/admin/llamar_y_marcar', methods=['POST'])
@role_required('admin')  # Solo administradores pueden enviar la orden de llamar
def llamar_y_marcar():
    if "usuario" not in session:
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    
    try:
        data = request.get_json()
        cita_id = data.get('citaId')
        nombre = data.get('nombre')

        if not cita_id or not nombre:
            return jsonify({'success': False, 'error': 'Faltan datos'}), 400

        # Paso A: Flask actualiza Supabase de forma segura
        supabase.table('citas').update({'fue_llamado': True}).eq('id', cita_id).execute()
        
        # Paso B: Flask pone el anuncio en la cola para el streaming
        announcement_queue.put(nombre)
        
        return jsonify({'success': True})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/admin/pagos', methods=['GET', 'POST'])
def registrar_pago():
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder", "error")
        return redirect(url_for("login"))
    
    servicios = [
        ('ginecologica', 'Consulta ginecológica'),
        ('mama', 'Consulta de mama'),
        ('post', 'Post quirúrgico'),
        ('biopsia', 'Biopsia'),
        ('resultados', 'Entrega de resultados')
    ]

    if request.method == 'POST':
        # ... (La lógica POST no necesita cambios) ...
        try:
            cita_id = request.form['cita_id']
            monto = request.form['monto']
            metodo_pago = request.form['metodo_pago']
            fecha_pago = request.form['fecha_pago']
            notas = request.form.get('notas', '')
            motivo_actualizado = request.form['motivo']

            supabase.table('pagos').insert({
                'cita_id': cita_id, 'monto': monto, 'metodo_pago': metodo_pago,
                'fecha_pago': fecha_pago, 'notas': notas
            }).execute()

            supabase.table('citas').update({
                'pagado': True, 'motivo': motivo_actualizado
            }).eq('id', cita_id).execute()

            flash('✅ Pago registrado correctamente y motivo actualizado.', 'success')
        except Exception as e:
            flash(f'❌ Error al registrar el pago: {e}', 'error')
        
        fecha_actual = request.args.get('fecha', date.today().strftime('%Y-%m-%d'))

        if session.get('role') == 'admin':
            return redirect(url_for('registrar_pago', fecha=fecha_actual))
        if session.get('role') == 'secretaria':
            return redirect(url_for('secretaria_pagos', fecha=fecha_actual))

    # --- LÓGICA GET ACTUALIZADA ---
    filtro_fecha = request.args.get("fecha", date.today().strftime('%Y-%m-%d'))
    config = get_configuracion()
    
    # --- 1. OBTENER CITAS PENDIENTES DE PAGO (como antes) ---
    citas_por_pagar = []
    try:
        response_pendientes = supabase.table('citas').select('*') \
            .eq('fecha', filtro_fecha).eq('pagado', False) \
            .order('orden', desc=False).execute()
        citas_por_pagar = response_pendientes.data
    except Exception as e:
        flash(f'❌ Error al cargar citas pendientes: {e}', 'error')

    # --- 2. NUEVO: OBTENER PAGOS YA REALIZADOS para la fecha de la cita ---
    pagos_realizados = []
    try:
        response_pagados = supabase.table('pagos').select('*, citas!inner(nombre, motivo, fecha)') \
            .eq('citas.fecha', filtro_fecha) \
            .order('id', desc=True).execute()
        
        # # Imprimimos la respuesta cruda en la consola para inspeccionarla
        # print("----------- DATOS CRUDOS DE SUPABASE (pagos realizados) -----------")
        # print(response_pagados.data)
        # print(f"----------- FILTRANDO POR FECHA: {filtro_fecha} -----------")

        pagos_realizados = response_pagados.data
    except Exception as e:
        flash(f'❌ Error al cargar pagos realizados: {e}', 'error')
    
    # --- 3. NUEVO: CALCULAR TOTALES ---
    total_pagado = sum(float(pago.get('monto', 0) or 0) for pago in pagos_realizados)
    
    total_pendiente = 0
    for cita in citas_por_pagar:
        clave_precio = f"precio_{cita.get('motivo', '')}"
        precio_str = config.get(clave_precio, '0')
        try:
            total_pendiente += float(precio_str or 0)
        except (ValueError, TypeError):
            # Ignora si el precio no es un número válido
            pass

    return render_template(
        "pagos.html", 
        citas_por_pagar=citas_por_pagar, 
        pagos_realizados=pagos_realizados, # <- Pasamos la nueva lista
        total_pagado=total_pagado,         # <- Pasamos el nuevo total
        total_pendiente=total_pendiente,   # <- Pasamos el nuevo total
        configuracion=config,
        filtro_fecha=filtro_fecha,
        date=date,
        servicios=servicios
    )

@app.route('/admin/reporte_pagos', methods=['GET'])
def reporte_pagos():
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder", "error")
        return redirect(url_for("login"))

    fecha_desde = request.args.get('fecha_desde')
    fecha_hasta = request.args.get('fecha_hasta')

    pagos = []
    total_reporte = 0

    if fecha_desde and fecha_hasta:
        try:
            # ===== MODIFICACIÓN AQUÍ: añadimos 'fecha' al select de citas =====
            response = supabase.table('pagos') \
                .select('*, citas(nombre, motivo, fecha)') \
                .gte('fecha_pago', fecha_desde) \
                .lte('fecha_pago', fecha_hasta) \
                .order('fecha_pago', desc=True) \
                .execute()
            
            pagos = response.data
            total_reporte = sum(float(pago.get('monto', 0) or 0) for pago in pagos)

        except Exception as e:
            flash(f'❌ Error al generar el reporte: {e}', 'error')

    return render_template(
        'reporte_pagos.html',
        pagos=pagos,
        total_reporte=total_reporte,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta
    )

# La gestión de usuarios ya está implementada arriba


@app.route("/admin/usuarios/editar/<int:user_id>", methods=["GET", "POST"])
@role_required('admin')  # Solo administradores pueden editar usuarios
def editar_usuario(user_id):

    if request.method == "POST":
        username = request.form.get("username")
        role = request.form.get("role")
        password = request.form.get("password")
        password_repeat = request.form.get("password_repeat")
        
        # --- Validaciones ---
        if not username or not role:
            flash("❌ El nombre de usuario y el rol son obligatorios.", "error")
            return redirect(url_for("editar_usuario", user_id=user_id))
        
        # Verificar si el nuevo username ya lo tiene OTRO usuario
        existing_user = supabase.table("usuarios").select("id").eq("username", username).neq("id", user_id).execute().data
        if existing_user:
            flash(f"❌ El nombre de usuario '{username}' ya está en uso por otro usuario.", "error")
            return redirect(url_for("editar_usuario", user_id=user_id))

        update_data = { "username": username, "role": role }

        # Si se proporcionó una nueva contraseña, validarla y hashearla
        if password:
            if password != password_repeat:
                flash("❌ Las nuevas contraseñas no coinciden.", "error")
                return redirect(url_for("editar_usuario", user_id=user_id))
            update_data["password_hash"] = generate_password_hash(password)
        
        try:
            supabase.table("usuarios").update(update_data).eq("id", user_id).execute()
            flash("✅ Usuario actualizado correctamente.", "success")
            return redirect(url_for("gestion_usuarios"))
        except Exception as e:
            flash(f"❌ Error al actualizar el usuario: {e}", "error")
            return redirect(url_for("editar_usuario", user_id=user_id))

    # Lógica para mostrar el formulario de edición (método GET)
    try:
        usuario = supabase.table("usuarios").select("*").eq("id", user_id).single().execute().data
        if not usuario:
            flash("❌ Usuario no encontrado.", "error")
            return redirect(url_for("gestion_usuarios"))
    except Exception as e:
        flash(f"❌ Error al buscar el usuario: {e}", "error")
        return redirect(url_for("gestion_usuarios"))
        
    return render_template("editar_usuario.html", usuario=usuario)


# La función para eliminar usuarios ya está implementada arriba

# ============================================
# --- FIN: GESTIÓN DE USUARIOS ---
# ============================================

@app.route("/secretaria")
@role_required('secretaria') # Solo secretarias pueden acceder aquí
def secretaria_dashboard():
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder al panel", "error")
        return redirect(url_for("login"))

    filtro_fecha = request.args.get("fecha")
    
    # Prepara la consulta base, AHORA ORDENANDO POR LA NUEVA COLUMNA 'orden'
    query = supabase.table("citas").select("*").order("orden", desc=False) # desc=False es ascendente (0, 1, 2...)

    if filtro_fecha is None:
        filtro_fecha = date.today().strftime('%Y-%m-%d')
        query = query.eq("fecha", filtro_fecha)
    elif filtro_fecha:
        query = query.eq("fecha", filtro_fecha)
    
    citas = query.execute().data
    bloqueadas = supabase.table("fechas_bloqueadas").select("*").order("fecha", desc=True).execute().data

    return render_template("secretaria_admin.html", citas=citas, bloqueadas=bloqueadas, filtro_fecha=filtro_fecha)

# @app.route("/secretaria")
# @role_required('secretaria') # Solo secretarias pueden acceder aquí
# def secretaria_dashboard():
#     # La lógica es muy similar al panel de admin: mostrar citas del día
#     filtro_fecha = request.args.get("fecha", date.today().strftime('%Y-%m-%d'))
    
#     query = supabase.table("citas").select("*").order("orden", desc=False).eq("fecha", filtro_fecha)
#     citas = query.execute().data
    
#     # Renderizamos una nueva plantilla específica para la secretaria
#     return render_template("secretaria_admin.html", citas=citas, filtro_fecha=filtro_fecha)

# @app.route('/secretaria/pagos', methods=['GET', 'POST'])
# @role_required('secretaria') # Solo secretarias pueden acceder aquí
# def secretaria_registrar_pago():
#     if "usuario" not in session:
#         flash("⚠️ Debes iniciar sesión para acceder", "error")
#         return redirect(url_for("login"))
    
#     servicios = [
#         ('ginecologica', 'Consulta ginecológica'),
#         ('mama', 'Consulta de mama'),
#         ('post', 'Post quirúrgico'),
#         ('biopsia', 'Biopsia'),
#         ('resultados', 'Entrega de resultados')
#     ]

#     if request.method == 'POST':
#         # ... (La lógica POST no necesita cambios) ...
#         try:
#             cita_id = request.form['cita_id']
#             monto = request.form['monto']
#             metodo_pago = request.form['metodo_pago']
#             fecha_pago = request.form['fecha_pago']
#             notas = request.form.get('notas', '')
#             motivo_actualizado = request.form['motivo']

#             supabase.table('pagos').insert({
#                 'cita_id': cita_id, 'monto': monto, 'metodo_pago': metodo_pago,
#                 'fecha_pago': fecha_pago, 'notas': notas
#             }).execute()

#             supabase.table('citas').update({
#                 'pagado': True, 'motivo': motivo_actualizado
#             }).eq('id', cita_id).execute()

#             flash('✅ Pago registrado correctamente y motivo actualizado.', 'success')
#         except Exception as e:
#             flash(f'❌ Error al registrar el pago: {e}', 'error')
        
#         fecha_actual = request.args.get('fecha', date.today().strftime('%Y-%m-%d'))
#         return redirect(url_for('registrar_pago', fecha=fecha_actual))

#     # --- LÓGICA GET ACTUALIZADA ---
#     filtro_fecha = request.args.get("fecha", date.today().strftime('%Y-%m-%d'))
#     config = get_configuracion()
    
#     # --- 1. OBTENER CITAS PENDIENTES DE PAGO (como antes) ---
#     citas_por_pagar = []
#     try:
#         response_pendientes = supabase.table('citas').select('*') \
#             .eq('fecha', filtro_fecha).eq('pagado', False) \
#             .order('orden', desc=False).execute()
#         citas_por_pagar = response_pendientes.data
#     except Exception as e:
#         flash(f'❌ Error al cargar citas pendientes: {e}', 'error')

#     # --- 2. NUEVO: OBTENER PAGOS YA REALIZADOS para la fecha de la cita ---
#     pagos_realizados = []
#     try:
#         response_pagados = supabase.table('pagos').select('*, citas!inner(nombre, motivo, fecha)') \
#             .eq('citas.fecha', filtro_fecha) \
#             .order('id', desc=True).execute()
        
#         # # Imprimimos la respuesta cruda en la consola para inspeccionarla
#         # print("----------- DATOS CRUDOS DE SUPABASE (pagos realizados) -----------")
#         # print(response_pagados.data)
#         # print(f"----------- FILTRANDO POR FECHA: {filtro_fecha} -----------")

#         pagos_realizados = response_pagados.data
#     except Exception as e:
#         flash(f'❌ Error al cargar pagos realizados: {e}', 'error')
    
#     # --- 3. NUEVO: CALCULAR TOTALES ---
#     total_pagado = sum(float(pago.get('monto', 0) or 0) for pago in pagos_realizados)
    
#     total_pendiente = 0
#     for cita in citas_por_pagar:
#         clave_precio = f"precio_{cita.get('motivo', '')}"
#         precio_str = config.get(clave_precio, '0')
#         try:
#             total_pendiente += float(precio_str or 0)
#         except (ValueError, TypeError):
#             # Ignora si el precio no es un número válido
#             pass

#     return render_template(
#         "secretaria_pagos.html", 
#         citas_por_pagar=citas_por_pagar, 
#         pagos_realizados=pagos_realizados, # <- Pasamos la nueva lista
#         total_pagado=total_pagado,         # <- Pasamos el nuevo total
#         total_pendiente=total_pendiente,   # <- Pasamos el nuevo total
#         configuracion=config,
#         filtro_fecha=filtro_fecha,
#         date=date,
#         servicios=servicios
#     )

@app.route('/secretaria/pagos', methods=['GET', 'POST'])
@role_required('secretaria')  # Solo secretarias pueden acceder aquí
def secretaria_registrar_pago():
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder", "error")
        return redirect(url_for("login"))
    
    # 🔹 Servicios cargados dinámicamente
    servicios = get_servicios()

    if request.method == 'POST':
        try:
            cita_id = request.form['cita_id']
            monto = request.form['monto']
            metodo_pago = request.form['metodo_pago']
            fecha_pago = request.form['fecha_pago']
            notas = request.form.get('notas', '')
            motivo_actualizado = request.form['motivo']

            # Insertar en tabla pagos
            supabase.table('pagos').insert({
                'cita_id': cita_id,
                'monto': monto,
                'metodo_pago': metodo_pago,
                'fecha_pago': fecha_pago,
                'notas': notas
            }).execute()

            # Actualizar cita como pagada y actualizar motivo
            supabase.table('citas').update({
                'pagado': True,
                'motivo': motivo_actualizado
            }).eq('id', cita_id).execute()

            flash('✅ Pago registrado correctamente y motivo actualizado.', 'success')
        except Exception as e:
            flash(f'❌ Error al registrar el pago: {e}', 'error')
        
        fecha_actual = request.args.get('fecha', date.today().strftime('%Y-%m-%d'))
        return redirect(url_for('secretaria_registrar_pago', fecha=fecha_actual))

    # ==========================
    # 🔹 LÓGICA GET
    # ==========================
    filtro_fecha = request.args.get("fecha", date.today().strftime('%Y-%m-%d'))
    config = get_configuracion()
    
    # --- 1. OBTENER CITAS PENDIENTES DE PAGO ---
    citas_por_pagar = []
    try:
        response_pendientes = supabase.table('citas').select('*') \
            .eq('fecha', filtro_fecha).eq('pagado', False) \
            .order('orden', desc=False).execute()
        citas_por_pagar = response_pendientes.data
    except Exception as e:
        flash(f'❌ Error al cargar citas pendientes: {e}', 'error')

    # --- 2. OBTENER PAGOS YA REALIZADOS ---
    pagos_realizados = []
    try:
        response_pagados = supabase.table('pagos').select('*, citas!inner(nombre, motivo, fecha)') \
            .eq('citas.fecha', filtro_fecha) \
            .order('id', desc=True).execute()
        pagos_realizados = response_pagados.data
    except Exception as e:
        flash(f'❌ Error al cargar pagos realizados: {e}', 'error')
    
    # --- 3. CALCULAR TOTALES ---
    total_pagado = sum(float(pago.get('monto', 0) or 0) for pago in pagos_realizados)

    # Crear un mapa de precios desde servicios
    precios_servicios = {s['nombre']: float(s.get('precio', 0) or 0) for s in servicios}

    total_pendiente = 0
    for cita in citas_por_pagar:
        precio = precios_servicios.get(cita.get('motivo', ''), 0)
        total_pendiente += precio

    # ==========================
    # 🔹 RETORNO FINAL
    # ==========================
    return render_template(
        "secretaria_pagos.html", 
        citas_por_pagar=citas_por_pagar, 
        pagos_realizados=pagos_realizados,
        total_pagado=total_pagado,
        total_pendiente=total_pendiente,
        configuracion=config,
        filtro_fecha=filtro_fecha,
        date=date,
        servicios=servicios,
        fechas_bloqueadas=[]  # Added empty list as default value
    )


# @app.route("/admin/registrar_cita_admin", methods=["GET", "POST"])
# @role_required('admin', 'secretaria') # Protegemos para que solo admin y secretaria puedan acceder
# def registrar_cita_admin():
#     config = get_configuracion()
    
#     # Obtenemos las fechas bloqueadas manualmente, ya que esas sí deben respetarse
#     try:
#         fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
#         fechas_bloqueadas = [f["fecha"] for f in fechas_bloqueadas_data]
#     except Exception as e:
#         print(f"Error al obtener fechas bloqueadas para admin: {e}")
#         fechas_bloqueadas = []

#     if request.method == "POST":
#         fecha_str = request.form["fecha"]
#         fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()

#         # --- VALIDACIÓN DE BACKEND (SIN LÍMITE DE PACIENTES) ---
#         # 1. Validar fines de semana según configuración
#         if config.get('bloquear_sabados') == 'true' and fecha_obj.weekday() == 5:
#             flash("⚠️ La configuración actual bloquea los sábados, pero se permite el registro.", "error") # Advertencia en lugar de error
#         if config.get('bloquear_domingos') == 'true' and fecha_obj.weekday() == 6:
#             flash("⚠️ La configuración actual bloquea los domingos, pero se permite el registro.", "error") # Advertencia

#         # 2. Validar si la fecha está bloqueada manualmente
#         if fecha_str in fechas_bloqueadas:
#             flash(f"❌ La fecha {fecha_str} está bloqueada manualmente y no se puede registrar la cita.", "error")
#             return redirect(url_for("registrar_cita_admin"))

#         # 3. SE OMITE LA VALIDACIÓN DE 'dias_llenos'. ¡Esta es la clave!

#         # --- Procesar y guardar la cita (lógica existente) ---
#         nombre = request.form["nombre"]
#         telefono = request.form["telefono"]
#         motivo = request.form["motivo"]
#         numero_seguro_medico = request.form["numero_seguro_medico"]
#         nombre_seguro_medico = request.form["nombre_seguro_medico"]

#         data = {
#             "nombre": nombre, "telefono": telefono, "fecha": fecha_str,
#             "motivo": motivo, "numero_seguro_medico": numero_seguro_medico,
#             "nombre_seguro_medico": nombre_seguro_medico,
#             # Campos opcionales o con valores por defecto
#             "email": "", "tanda": "", "tipo_seguro_medico": ""
#         }
        
#         try:
#             supabase.table("citas").insert(data).execute()
#             flash("✅ Cita registrada correctamente desde el panel de administración.", "success")
#             # Opcional: Enviar notificación a Telegram
#             mensaje = (f"Nueva cita registrada (Admin):\n"
#                        f"Nombre: {nombre}\nTeléfono: {telefono}\nFecha: {fecha_str}\n"
#                        f"Motivo: {motivo}\nSeguro: {nombre_seguro_medico} ({numero_seguro_medico})")
#             send_telegram_message(mensaje)
#         except Exception as e:
#             flash(f"❌ Error al registrar la cita: {e}", "error")

#         return redirect(url_for("registrar_cita_admin"))

#     # --- LÓGICA PARA GET ---
#     # Renderizamos el nuevo template. La clave es pasar una lista vacía para 'dias_llenos'.
#     return render_template(
#         "admin_registrar_cita.html", 
#         fechas_bloqueadas=fechas_bloqueadas, 
#         dias_llenos=[],  # <-- ¡AQUÍ ESTÁ LA MAGIA! El script no bloqueará ningún día por estar lleno.
#         configuracion=config
#     )

# EN app.py

@app.route("/admin/registrar_cita_admin", methods=["GET", "POST"])
@role_required('admin', 'secretaria') # Protegemos para que solo admin y secretaria puedan acceder
def registrar_cita_admin():
    config = get_configuracion()
    
    # Obtenemos las fechas bloqueadas manualmente, ya que esas sí deben respetarse
    try:
        fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
        fechas_bloqueadas = [f["fecha"] for f in fechas_bloqueadas_data]
    except Exception as e:
        print(f"Error al obtener fechas bloqueadas para admin: {e}")
        fechas_bloqueadas = []

    if request.method == "POST":
        fecha_str = request.form["fecha"]
        fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()

        # --- VALIDACIÓN DE BACKEND (SIN LÍMITE DE PACIENTES) ---
        if config.get('bloquear_sabados') == 'true' and fecha_obj.weekday() == 5:
            flash("⚠️ La configuración actual bloquea los sábados, pero se permite el registro.", "warning")
        if config.get('bloquear_domingos') == 'true' and fecha_obj.weekday() == 6:
            flash("⚠️ La configuración actual bloquea los domingos, pero se permite el registro.", "warning")

        if fecha_str in fechas_bloqueadas:
            flash(f"❌ La fecha {fecha_str} está bloqueada manualmente y no se puede registrar la cita.", "error")
            return redirect(url_for("registrar_cita_admin"))

        # --- INICIO DE LA MODIFICACIÓN ---
        # Recolectamos todos los datos del formulario, incluyendo la cédula
        cedula_raw = request.form.get("cedula", "").strip()
        nombre = request.form["nombre"].strip()
        telefono = request.form["telefono"].strip()
        motivo = request.form["motivo"].strip()
        nombre_seguro_medico = request.form["nombre_seguro_medico"].strip()
        numero_seguro_medico = request.form["numero_seguro_medico"].strip()

        # Validaciones básicas
        if not nombre or not telefono or not fecha_str or not motivo:
            flash("❌ Nombre, teléfono, fecha y motivo son campos obligatorios.", "error")
            return redirect(url_for("registrar_cita_admin"))

        # Lógica para guardar/actualizar paciente (reutilizada del formulario público)
        try:
            paciente_data = {
                "nombre_completo": nombre,
                "telefono": telefono,
                "nombre_seguro_medico": nombre_seguro_medico,
                "numero_seguro_medico": numero_seguro_medico
            }
            if cedula_raw:
                paciente_data["cedula"] = cedula_raw
                supabase.table("pacientes").upsert(paciente_data, on_conflict="cedula").execute()
            else:
                # Si no hay cédula, podemos buscar por nombre y teléfono para evitar duplicados
                existing = supabase.table("pacientes").select("id").eq("nombre_completo", nombre).eq("telefono", telefono).execute()
                if existing.data:
                    supabase.table("pacientes").update(paciente_data).eq("id", existing.data[0]['id']).execute()
                else:
                    supabase.table("pacientes").insert(paciente_data).execute()
        except Exception as e:
            print(f"⚠️ Error al guardar/actualizar paciente desde el panel de admin: {e}")
            flash("⚠️ Hubo un problema al guardar los datos maestros del paciente, pero la cita se registrará igualmente.", "warning")
        
# --- NUEVO: VALIDACIÓN DE CITA DUPLICADA ---
        if verificar_cita_duplicada(fecha_str, cedula_raw, nombre, telefono):
            flash("❌ Ya existe una cita registrada para este paciente en la misma fecha. Por favor, verifique.", "error")
            return redirect(url_for("registrar_cita_admin"))
        # --- FIN DE LA VALIDACIÓN ---

        # Preparar datos para la tabla de citas
        data_cita = {
            "nombre": nombre, "telefono": telefono, "fecha": fecha_str,
            "motivo": motivo, "numero_seguro_medico": numero_seguro_medico,
            "nombre_seguro_medico": nombre_seguro_medico,
            "cedula": cedula_raw if cedula_raw else None, # Guardar la cédula
            "email": "", "tanda": "", "tipo_seguro_medico": ""
        }
        
        try:
            supabase.table("citas").insert(data_cita).execute()
            flash("✅ Cita registrada correctamente desde el panel de administración.", "success")
            
            # Notificación a Telegram mejorada
            mensaje = (f"📝 Nueva cita registrada (Admin/Secretaria):\n"
                       f"Nombre: {nombre}\n"
                       f"Teléfono: {telefono}\n"
                       f"Cédula: {cedula_raw or 'No provista'}\n"
                       f"Fecha: {fecha_str}\n"
                       f"Motivo: {motivo}\n"
                       f"Seguro: {nombre_seguro_medico or 'No provisto'}")
            send_telegram_message(mensaje)

        except Exception as e:
            flash(f"❌ Error al registrar la cita: {e}", "error")
        # --- FIN DE LA MODIFICACIÓN ---

        return redirect(url_for("registrar_cita_admin"))

    # --- LÓGICA PARA GET (sin cambios) ---
    return render_template(
        "admin_registrar_cita.html", 
        fechas_bloqueadas=fechas_bloqueadas, 
        dias_llenos=[],
        configuracion=config
    )

@app.route("/secretaria/registrar_cita_secretaria", methods=["GET", "POST"])
@role_required('admin', 'secretaria') # Protegemos para que solo admin y secretaria puedan acceder
def registrar_cita_secretaria():
    config = get_configuracion()
    
    # Obtenemos las fechas bloqueadas manualmente, ya que esas sí deben respetarse
    try:
        fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
        fechas_bloqueadas = [f["fecha"] for f in fechas_bloqueadas_data]
    except Exception as e:
        print(f"Error al obtener fechas bloqueadas para admin: {e}")
        fechas_bloqueadas = []

    if request.method == "POST":
        fecha_str = request.form["fecha"]
        fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()

        # --- VALIDACIÓN DE BACKEND (SIN LÍMITE DE PACIENTES) ---
        # 1. Validar fines de semana según configuración
        if config.get('bloquear_sabados') == 'true' and fecha_obj.weekday() == 5:
            flash("⚠️ La configuración actual bloquea los sábados, pero se permite el registro.", "error") # Advertencia en lugar de error
        if config.get('bloquear_domingos') == 'true' and fecha_obj.weekday() == 6:
            flash("⚠️ La configuración actual bloquea los domingos, pero se permite el registro.", "error") # Advertencia

        # 2. Validar si la fecha está bloqueada manualmente
        if fecha_str in fechas_bloqueadas:
            flash(f"❌ La fecha {fecha_str} está bloqueada manualmente y no se puede registrar la cita.", "error")
            return redirect(url_for("registrar_cita_secretaria"))

        # 3. SE OMITE LA VALIDACIÓN DE 'dias_llenos'. ¡Esta es la clave!

        # --- Procesar y guardar la cita (lógica existente) ---
        nombre = request.form["nombre"]
        telefono = request.form["telefono"]
        motivo = request.form["motivo"]
        numero_seguro_medico = request.form["numero_seguro_medico"]
        nombre_seguro_medico = request.form["nombre_seguro_medico"]
        cedula = request.form.get("cedula", "")  # Obtener la cédula, si está vacía será ""

# --- NUEVO: VALIDACIÓN DE CITA DUPLICADA ---
        if verificar_cita_duplicada(fecha_str, cedula, nombre, telefono):
            flash("❌ Ya existe una cita registrada para este paciente en la misma fecha. Por favor, verifique.", "error")
            return redirect(url_for("registrar_cita_secretaria"))
        # --- FIN DE LA VALIDACIÓN ---

        data = {
            "nombre": nombre, "telefono": telefono, "fecha": fecha_str,
            "motivo": motivo, "numero_seguro_medico": numero_seguro_medico,
            "nombre_seguro_medico": nombre_seguro_medico, "cedula": cedula,
            # Campos opcionales o con valores por defecto
            "email": "", "tanda": "", "tipo_seguro_medico": ""
        }
        
        try:
            supabase.table("citas").insert(data).execute()
            flash("✅ Cita registrada correctamente desde el panel de administración.", "success")
            # Opcional: Enviar notificación a Telegram
            mensaje = (f"Nueva cita registrada (Secretaria):\n"
                       f"Nombre: {nombre}\nTeléfono: {telefono}\nFecha: {fecha_str}\n"
                       f"Motivo: {motivo}\nSeguro: {nombre_seguro_medico} ({numero_seguro_medico})")
            send_telegram_message(mensaje)
        except Exception as e:
            flash(f"❌ Error al registrar la cita: {e}", "error")

        return redirect(url_for("registrar_cita_secretaria"))

    # --- LÓGICA PARA GET ---
    # Renderizamos el nuevo template. La clave es pasar una lista vacía para 'dias_llenos'.
    return render_template(
        "secretaria_registrar_cita.html", 
        fechas_bloqueadas=fechas_bloqueadas, 
        dias_llenos=[],  # <-- ¡AQUÍ ESTÁ LA MAGIA! El script no bloqueará ningún día por estar lleno.
        configuracion=config
    )

# @app.route('/admin/registrar_pagos', methods=['GET', 'POST'])
# def admin_registrar_pago():
#     if "usuario" not in session:
#         flash("⚠️ Debes iniciar sesión para acceder", "error")
#         return redirect(url_for("login"))
    
#     servicios = [
#         ('ginecologica', 'Consulta ginecológica'),
#         ('mama', 'Consulta de mama'),
#         ('post', 'Post quirúrgico'),
#         ('biopsia', 'Biopsia'),
#         ('resultados', 'Entrega de resultados')
#     ]

#     if request.method == 'POST':
#         # ... (La lógica POST no necesita cambios) ...
#         try:
#             cita_id = request.form['cita_id']
#             monto = request.form['monto']
#             metodo_pago = request.form['metodo_pago']
#             fecha_pago = request.form['fecha_pago']
#             notas = request.form.get('notas', '')
#             motivo_actualizado = request.form['motivo']

#             supabase.table('pagos').insert({
#                 'cita_id': cita_id, 'monto': monto, 'metodo_pago': metodo_pago,
#                 'fecha_pago': fecha_pago, 'notas': notas
#             }).execute()

#             supabase.table('citas').update({
#                 'pagado': True, 'motivo': motivo_actualizado
#             }).eq('id', cita_id).execute()

#             flash('✅ Pago registrado correctamente y motivo actualizado.', 'success')
#         except Exception as e:
#             flash(f'❌ Error al registrar el pago: {e}', 'error')
        
#         fecha_actual = request.args.get('fecha', date.today().strftime('%Y-%m-%d'))

#         if session.get('role') == 'admin':
#             return redirect(url_for('admin_registrar_pago', fecha=fecha_actual))

#     # --- LÓGICA GET ACTUALIZADA ---
#     filtro_fecha = request.args.get("fecha", date.today().strftime('%Y-%m-%d'))
#     config = get_configuracion()
    
#     # --- 1. OBTENER CITAS PENDIENTES DE PAGO (como antes) ---
#     citas_por_pagar = []
#     try:
#         response_pendientes = supabase.table('citas').select('*') \
#             .eq('fecha', filtro_fecha).eq('pagado', False) \
#             .order('orden', desc=False).execute()
#         citas_por_pagar = response_pendientes.data
#     except Exception as e:
#         flash(f'❌ Error al cargar citas pendientes: {e}', 'error')

#     # --- 2. NUEVO: OBTENER PAGOS YA REALIZADOS para la fecha de la cita ---
#     pagos_realizados = []
#     try:
#         response_pagados = supabase.table('pagos').select('*, citas!inner(nombre, motivo, fecha)') \
#             .eq('citas.fecha', filtro_fecha) \
#             .order('id', desc=True).execute()
        
#         # # Imprimimos la respuesta cruda en la consola para inspeccionarla
#         # print("----------- DATOS CRUDOS DE SUPABASE (pagos realizados) -----------")
#         # print(response_pagados.data)
#         # print(f"----------- FILTRANDO POR FECHA: {filtro_fecha} -----------")

#         pagos_realizados = response_pagados.data
#     except Exception as e:
#         flash(f'❌ Error al cargar pagos realizados: {e}', 'error')
    
#     # --- 3. NUEVO: CALCULAR TOTALES ---
#     total_pagado = sum(float(pago.get('monto', 0) or 0) for pago in pagos_realizados)
    
#     total_pendiente = 0
#     for cita in citas_por_pagar:
#         clave_precio = f"precio_{cita.get('motivo', '')}"
#         precio_str = config.get(clave_precio, '0')
#         print(cita.get('fecha', 'N/A'))
#         try:
#             total_pendiente += float(precio_str or 0)
#         except (ValueError, TypeError):
#             # Ignora si el precio no es un número válido
#             pass
#     # =================================================================
#     # NUEVO: OBTENER IDs DE CITAS QUE YA TIENEN SEGUIMIENTO
#     # =================================================================
#     citas_con_seguimiento = set()
#     if pagos_realizados:
#         try:
#             # 1. Obtener la lista de IDs de las citas pagadas
#             ids_citas_pagadas = [pago['cita_id'] for pago in pagos_realizados]
            
#             # 2. Consultar la tabla 'seguimiento' para ver cuáles de esos IDs ya existen
#             seguimientos = supabase.table('seguimiento').select('cita_id').in_('cita_id', ids_citas_pagadas).execute().data
            
#             # 3. Crear un conjunto (set) con los IDs para una búsqueda rápida en el template
#             citas_con_seguimiento = {s['cita_id'] for s in seguimientos}
#         except Exception as e:
#             flash(f'❌ Error al verificar seguimientos: {e}', 'error')
#     # =================================================================

#     return render_template(
#         "admin_pagos.html", 
#         citas_por_pagar=citas_por_pagar, 
#         pagos_realizados=pagos_realizados, # <- Pasamos la nueva lista
#         total_pagado=total_pagado,         # <- Pasamos el nuevo total
#         total_pendiente=total_pendiente,   # <- Pasamos el nuevo total
#         configuracion=config,
#         filtro_fecha=filtro_fecha,
#         date=date,
#         servicios=servicios,
#         citas_con_seguimiento=citas_con_seguimiento, # <-- PASAMOS LA NUEVA VARIABLE
#         fechas_bloqueadas=[] # Inicializamos como lista vacía para evitar el error
#     )

@app.route('/admin/registrar_pagos', methods=['GET', 'POST'])
def admin_registrar_pago():
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder", "error")
        return redirect(url_for("login"))
    
    # 🔹 Servicios cargados desde la función (dinámico, no hardcodeado)
    servicios = get_servicios()

    if request.method == 'POST':
        try:
            cita_id = request.form['cita_id']
            monto = request.form['monto']
            metodo_pago = request.form['metodo_pago']
            fecha_pago = request.form['fecha_pago']
            notas = request.form.get('notas', '')
            motivo_actualizado = request.form['motivo']

            # Insertar en tabla pagos
            supabase.table('pagos').insert({
                'cita_id': cita_id,
                'monto': monto,
                'metodo_pago': metodo_pago,
                'fecha_pago': fecha_pago,
                'notas': notas
            }).execute()

            # Actualizar cita como pagada y actualizar motivo
            supabase.table('citas').update({
                'pagado': True,
                'motivo': motivo_actualizado
            }).eq('id', cita_id).execute()

            flash('✅ Pago registrado correctamente y motivo actualizado.', 'success')
        except Exception as e:
            flash(f'❌ Error al registrar el pago: {e}', 'error')
        
        fecha_actual = request.args.get('fecha', date.today().strftime('%Y-%m-%d'))

        if session.get('role') == 'admin':
            return redirect(url_for('admin_registrar_pago', fecha=fecha_actual))

    # ==========================
    # 🔹 LÓGICA GET
    # ==========================
    filtro_fecha = request.args.get("fecha", date.today().strftime('%Y-%m-%d'))
    config = get_configuracion()
    
    # --- 1. OBTENER CITAS PENDIENTES DE PAGO ---
    citas_por_pagar = []
    try:
        response_pendientes = supabase.table('citas').select('*') \
            .eq('fecha', filtro_fecha).eq('pagado', False) \
            .order('orden', desc=False).execute()
        citas_por_pagar = response_pendientes.data
    except Exception as e:
        flash(f'❌ Error al cargar citas pendientes: {e}', 'error')

    # --- 2. OBTENER PAGOS YA REALIZADOS ---
    pagos_realizados = []
    try:
        response_pagados = supabase.table('pagos').select('*, citas!inner(nombre, motivo, fecha)') \
            .eq('citas.fecha', filtro_fecha) \
            .order('id', desc=True).execute()
        pagos_realizados = response_pagados.data
    except Exception as e:
        flash(f'❌ Error al cargar pagos realizados: {e}', 'error')
    
    # --- 3. CALCULAR TOTALES ---
    total_pagado = sum(float(pago.get('monto', 0) or 0) for pago in pagos_realizados)

    # Crear un mapa de precios desde servicios
    precios_servicios = {s['nombre']: float(s.get('precio', 0) or 0) for s in servicios}

    total_pendiente = 0
    for cita in citas_por_pagar:
        precio = precios_servicios.get(cita.get('motivo', ''), 0)
        total_pendiente += precio

    # --- 4. OBTENER CITAS QUE YA TIENEN SEGUIMIENTO ---
    citas_con_seguimiento = set()
    if pagos_realizados:
        try:
            ids_citas_pagadas = [pago['cita_id'] for pago in pagos_realizados]
            seguimientos = supabase.table('seguimiento').select('cita_id') \
                .in_('cita_id', ids_citas_pagadas).execute().data
            citas_con_seguimiento = {s['cita_id'] for s in seguimientos}
        except Exception as e:
            flash(f'❌ Error al verificar seguimientos: {e}', 'error')

    # ==========================
    # 🔹 RETORNO FINAL
    # ==========================
    return render_template(
        "admin_pagos.html", 
        citas_por_pagar=citas_por_pagar, 
        pagos_realizados=pagos_realizados,
        total_pagado=total_pagado,
        total_pendiente=total_pendiente,
        configuracion=config,
        filtro_fecha=filtro_fecha,
        date=date,
        servicios=servicios,
        citas_con_seguimiento=citas_con_seguimiento,
        fechas_bloqueadas=[]
    )


@app.route('/admin/seguimiento_paciente', methods=['POST'])
@role_required('admin', 'secretaria') # Permitir a ambos roles
def seguimiento_paciente():
    try:
        cita_original_id = request.form['cita_id']
        necesita_cita = 'necesita_nueva_cita' in request.form

        # --- Obtener datos de la cita original para reutilizarlos ---
        cita_original = supabase.table("citas").select("*").eq("id", cita_original_id).single().execute().data
        if not cita_original:
            flash("❌ Error: No se encontró la cita original.", "error")
            return redirect(request.referrer or url_for('admin_registrar_pago')) # Usamos la ruta correcta

        paciente_nombre = cita_original.get('nombre')

        if necesita_cita:
            # --- CASO 1: Se necesita una nueva cita ---
            nueva_fecha = request.form['nueva_fecha']
            nueva_fecha_str = request.form['nueva_fecha']
            # =================================================================
            # INICIO DEL NUEVO BLOQUE DE VALIDACIÓN DE FECHA
            # =================================================================
            config = get_configuracion()

            # 1. Validar si la fecha está bloqueada manualmente
            fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
            fechas_bloqueadas = {f["fecha"] for f in fechas_bloqueadas_data}
            if nueva_fecha_str in fechas_bloqueadas:
                flash(f"❌ Error: La fecha {nueva_fecha_str} está bloqueada. Por favor, elija otra.", "error")
                return redirect(request.referrer)

            # 2. Validar fines de semana según configuración
            nueva_fecha_obj = datetime.strptime(nueva_fecha_str, '%Y-%m-%d').date()
            if config.get('bloquear_sabados') == 'true' and nueva_fecha_obj.weekday() == 5:
                flash("❌ Error: No se pueden agendar citas los sábados. Por favor, elija otra fecha.", "error")
                return redirect(request.referrer)
            if config.get('bloquear_domingos') == 'true' and nueva_fecha_obj.weekday() == 6:
                flash("❌ Error: No se pueden agendar citas los domingos. Por favor, elija otra fecha.", "error")
                return redirect(request.referrer)
            
            # =================================================================
            # NUEVO: Bloque de validación para evitar doble agendamiento
            # =================================================================
            # Buscamos si ya existe una cita para el mismo paciente en la nueva fecha seleccionada.
            cita_existente = supabase.table("citas") \
                                     .select("id") \
                                     .eq("nombre", paciente_nombre) \
                                     .eq("fecha", nueva_fecha) \
                                     .execute().data
            
            # Si la lista 'cita_existente' no está vacía, significa que se encontró un conflicto.
            if cita_existente:
                # Mostramos el mensaje de error solicitado en un "flash popup"
                flash(f"❌ Error: '{paciente_nombre}' ya tiene una cita agendada para el {nueva_fecha}. Por favor, asigne la cita en otra fecha.", "error")
                # Redirigimos de vuelta a la página de pagos sin hacer cambios.
                return redirect(request.referrer or url_for('registrar_pago'))
            # =================================================================
            # FIN DEL BLOQUE DE VALIDACIÓN
            # =================================================================

            # Si el código llega hasta aquí, significa que no hay conflicto y podemos crear la cita.
            nueva_cita_data = {
                "nombre": paciente_nombre,
                "telefono": cita_original.get('telefono'),
                "email": cita_original.get('email', ''), 
                "tanda": cita_original.get('tanda', ''),
                "fecha": nueva_fecha,
                "motivo": "ginecologica", # Un motivo por defecto, puede ser ajustado después
                "numero_seguro_medico": cita_original.get('numero_seguro_medico'),
                "nombre_seguro_medico": cita_original.get('nombre_seguro_medico'),
                "pagado": False,
                "fue_llamado": False
            }
            supabase.table("citas").insert(nueva_cita_data).execute()
            
            # Guardar registro en la tabla de seguimiento
            supabase.table("seguimiento").insert({
                "cita_id": cita_original_id,
                "necesita_nueva_cita": True
            }).execute()

            flash(f"✅ Nueva cita de seguimiento para {paciente_nombre} agendada para el {nueva_fecha}.", "success")
            
            mensaje_telegram = (
                f"🗓️ *Nueva Cita de Seguimiento Agendada*\n\n"
                f"👤 *Paciente:* {paciente_nombre}\n"
                f"➡️ *Próxima Cita:* {nueva_fecha}"
            )
            send_telegram_message(mensaje_telegram)

        else:
            # --- CASO 2: No se necesita nueva cita (sin cambios) ---
            motivo = request.form['motivo_no_cita']
            
            supabase.table("seguimiento").insert({
                "cita_id": cita_original_id,
                "necesita_nueva_cita": False,
                "motivo_no_cita": motivo
            }).execute()

            flash(f"✅ Seguimiento para {paciente_nombre} registrado: No necesita nueva cita.", "success")
            
            mensaje_telegram = (
                f"👍 *Seguimiento Completado (Sin Cita Próxima)*\n\n"
                f"👤 *Paciente:* {paciente_nombre}\n"
                f"📝 *Motivo:* {motivo}"
            )
            send_telegram_message(mensaje_telegram)

    except Exception as e:
        flash(f"❌ Ocurrió un error al procesar el seguimiento: {e}", "error")

    # Redirigir a la página anterior (la de pagos con el filtro de fecha)
    return redirect(request.referrer or url_for('admin_registrar_pago'))

@app.route("/admin/buscar_eliminar_cita", methods=["GET"])
@role_required('admin')
def buscar_eliminar_cita():
    """
    Página para buscar citas por fecha con el propósito de eliminarlas.
    """
    # 1. Obtener la fecha del filtro desde la URL (ej: /url?fecha=2023-10-27)
    filtro_fecha = request.args.get("fecha")
    citas = []

    # 2. Si se proporcionó una fecha, buscar las citas correspondientes
    if filtro_fecha:
        try:
            # Seleccionamos las citas para esa fecha, ordenadas como en el panel principal
            response = supabase.table("citas") \
                .select("*") \
                .eq("fecha", filtro_fecha) \
                .order("orden", desc=False) \
                .execute()
            citas = response.data
        except Exception as e:
            flash(f"❌ Error al buscar las citas: {e}", "error")

    # 3. Renderizar la nueva plantilla, pasándole las citas encontradas y la fecha
    return render_template("buscar_eliminar_cita.html", citas=citas, filtro_fecha=filtro_fecha)


# --- MEJORA OPCIONAL PERO RECOMENDADA ---
# Modificar la función existente `eliminar_cita` para una mejor experiencia de usuario.
# En lugar de redirigir siempre al panel principal, la haremos redirigir a la página anterior.

# Elimina o comenta tu función eliminar_cita actual y reemplázala con esta:

@app.route("/admin/eliminar_cita/<int:id>", methods=["POST"])
@role_required('admin') # Aseguramos que solo el admin pueda eliminar
def eliminar_cita(id):
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para realizar esta acción.", "error")
        return redirect(url_for("login"))
        
    try:
        # --- PASO 1: Obtener los detalles de la cita ANTES de eliminarla ---
        cita_a_eliminar = supabase.table("citas").select("*").eq("id", id).single().execute().data

        # Si no se encuentra la cita (quizás ya fue eliminada), mostramos un error.
        if not cita_a_eliminar:
            flash("❌ La cita que intentas eliminar no fue encontrada.", "error")
            return redirect(request.referrer or url_for("admin"))

        # --- PASO 2: Proceder con la eliminación ---
        supabase.table("citas").delete().eq("id", id).execute()

        # --- PASO 3: Construir y enviar la notificación a Telegram ---
        # Usamos .get() para evitar errores si algún campo estuviera vacío.
        nombre_paciente = cita_a_eliminar.get('nombre', 'No especificado')
        fecha_cita = cita_a_eliminar.get('fecha', 'No especificada')
        motivo_cita = cita_a_eliminar.get('motivo', 'No especificado')
        
        # Formateamos el mensaje para que se vea bien en Telegram (con markdown)
        mensaje_telegram = (
            f"🗑️ *Cita Eliminada del Sistema*\n\n"
            f"Se han borrado los datos de la siguiente cita:\n\n"
            f"👤 *Paciente:* {nombre_paciente}\n"
            f"🗓️ *Fecha:* {fecha_cita}\n"
            f"📋 *Motivo:* {motivo_cita}\n\n"
            f"Esta acción fue realizada por el usuario: *{session.get('usuario', 'Desconocido')}*"
        )
        
        send_telegram_message(mensaje_telegram)
        
        # --- PASO 4: Mostrar el mensaje de éxito en la interfaz ---
        flash("🗑️ Cita eliminada correctamente y notificación enviada.", "success")

    except Exception as e:
        flash(f"❌ Error al eliminar la cita: {e}", "error")

    # Redirige al usuario a la página desde la que vino (la de búsqueda),
    # o al panel de admin si no se puede determinar la página anterior.
    return redirect(request.referrer or url_for("admin"))

@app.route("/admin/buscar_eliminar_pago", methods=["GET"])
@role_required('admin')
def buscar_eliminar_pago():
    """
    Página para buscar pagos por rango de fechas y mostrarlos para su posible eliminación.
    """
    fecha_desde = request.args.get('fecha_desde')
    fecha_hasta = request.args.get('fecha_hasta')
    pagos = []

    if fecha_desde and fecha_hasta:
        try:
            # La consulta une la tabla 'pagos' con 'citas' para obtener el nombre del paciente
            response = supabase.table('pagos') \
                .select('*, citas(nombre, fecha)') \
                .gte('fecha_pago', fecha_desde) \
                .lte('fecha_pago', fecha_hasta) \
                .order('fecha_pago', desc=True) \
                .execute()
            pagos = response.data
        except Exception as e:
            flash(f'❌ Error al buscar los pagos: {e}', 'error')

    return render_template(
        'buscar_eliminar_pago.html',
        pagos=pagos,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta
    )


@app.route("/admin/eliminar_pago/<int:pago_id>", methods=["POST"])
@role_required('admin')
def eliminar_pago(pago_id):
    """
    Elimina un registro de pago, revierte el estado de la cita a 'no pagada'
    y envía una notificación a Telegram.
    """
    try:
        # --- PASO 1: Obtener todos los detalles del pago ANTES de eliminarlo ---
        # Hacemos un 'join' con la tabla de citas para obtener también el nombre del paciente.
        pago_a_eliminar = supabase.table("pagos") \
                                 .select("*, citas(nombre, fecha)") \
                                 .eq("id", pago_id) \
                                 .single() \
                                 .execute().data
        
        if not pago_a_eliminar:
            flash("❌ El pago que intentas eliminar no fue encontrado.", "error")
            return redirect(request.referrer or url_for('buscar_eliminar_pago'))

        # --- PASO 2: Extraer la información para la notificación y la lógica ---
        cita_id_asociada = pago_a_eliminar.get('cita_id')
        monto_pago = pago_a_eliminar.get('monto', 0)
        fecha_del_pago = pago_a_eliminar.get('fecha_pago', 'No especificada')
        
        # El nombre del paciente y la fecha de la cita vienen en un diccionario anidado
        cita_info = pago_a_eliminar.get('citas', {})
        nombre_paciente = cita_info.get('nombre', 'Desconocido')
        
        admin_usuario = session.get('usuario', 'Usuario Desconocido')

        # --- PASO 3: Construir el mensaje de Telegram ---
        mensaje_telegram = (
            f"🗑️ *Pago Eliminado del Sistema*\n\n"
            f"Se ha eliminado un registro de pago. La cita asociada ha sido marcada como 'No Pagada'.\n\n"
            f"👤 *Paciente:* {nombre_paciente}\n"
            f"💰 *Monto Eliminado:* RD$ {float(monto_pago):.2f}\n"
            f"🗓️ *Fecha del Pago:* {fecha_del_pago}\n\n"
            f"👨‍💻 *Acción realizada por:* {admin_usuario}"
        )

        # --- PASO 4: Ejecutar la lógica de eliminación en la base de datos ---
        # Primero se elimina el pago
        supabase.table("pagos").delete().eq("id", pago_id).execute()

        # Luego se revierte el estado de la cita
        if cita_id_asociada:
            supabase.table("citas").update({"pagado": False}).eq("id", cita_id_asociada).execute()
        
        # --- PASO 5: Enviar la notificación y el mensaje de éxito ---
        send_telegram_message(mensaje_telegram)
        
        flash("✅ Pago eliminado y notificación enviada. El estado de la cita fue revertido.", "success")

    except Exception as e:
        flash(f"❌ Error al eliminar el pago: {e}", "error")

    # Redirige al usuario a la página desde la que vino (la de búsqueda)
    return redirect(request.referrer or url_for('buscar_eliminar_pago'))

@app.route("/admin/estadisticas", methods=["GET"])
@role_required('admin')
def estadisticas_citas():
    """
    Genera y muestra estadísticas de citas basadas en un rango de fechas.
    """
    fecha_desde = request.args.get('fecha_desde')
    fecha_hasta = request.args.get('fecha_hasta')
    
    stats = {}
    citas_data = []

    if fecha_desde and fecha_hasta:
        try:
            # 1. Obtener todos los datos necesarios en una sola consulta
            response = supabase.table('citas') \
                .select('fecha, motivo') \
                .gte('fecha', fecha_desde) \
                .lte('fecha', fecha_hasta) \
                .execute()
            
            citas_data = response.data

            if citas_data:
                # 2. Calcular las estadísticas en Python
                total_citas = len(citas_data)

                # a) Conteo por motivo de cita
                motivos_count = {}
                for cita in citas_data:
                    motivo = cita.get('motivo', 'No especificado').replace('_', ' ').capitalize()
                    motivos_count[motivo] = motivos_count.get(motivo, 0) + 1
                
                # b) Conteo por mes
                meses_count = {}
                # Nombres de los meses en español
                nombres_meses = {
                    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
                    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
                }
                for cita in citas_data:
                    fecha_obj = datetime.strptime(cita['fecha'], '%Y-%m-%d')
                    # Usamos 'YYYY-MM' como clave para ordenar correctamente
                    mes_key = fecha_obj.strftime('%Y-%m')
                    # Usamos un nombre legible para mostrar
                    mes_display = f"{nombres_meses[fecha_obj.month]} {fecha_obj.year}"
                    
                    if mes_key not in meses_count:
                        meses_count[mes_key] = {'nombre': mes_display, 'cantidad': 0}
                    meses_count[mes_key]['cantidad'] += 1
                
                # c) Conteo por día de la semana
                dias_semana_count = {
                    0: {'nombre': 'Lunes', 'cantidad': 0},
                    1: {'nombre': 'Martes', 'cantidad': 0},
                    2: {'nombre': 'Miércoles', 'cantidad': 0},
                    3: {'nombre': 'Jueves', 'cantidad': 0},
                    4: {'nombre': 'Viernes', 'cantidad': 0},
                    5: {'nombre': 'Sábado', 'cantidad': 0},
                    6: {'nombre': 'Domingo', 'cantidad': 0}
                }
                for cita in citas_data:
                    fecha_obj = datetime.strptime(cita['fecha'], '%Y-%m-%d')
                    dia_index = fecha_obj.weekday() # Lunes=0, Domingo=6
                    if dia_index in dias_semana_count:
                        dias_semana_count[dia_index]['cantidad'] += 1

                # 3. Empaquetar todo para la plantilla
                stats = {
                    'total_citas': total_citas,
                    'por_motivo': sorted(motivos_count.items(), key=lambda item: item[1], reverse=True),
                    'por_mes': sorted(list(meses_count.values()), key=lambda item: item['nombre']),
                    'por_dia_semana': list(dias_semana_count.values())
                }

        except Exception as e:
            flash(f'❌ Error al generar las estadísticas: {e}', 'error')

    return render_template(
        'estadisticas.html',
        stats=stats,
        fecha_desde=fecha_desde,
        fecha_hasta=fecha_hasta
    )

# @app.route('/api/buscar_paciente/<string:cedula>')
# @public_route
# def buscar_paciente(cedula):
#     """
#     API endpoint para buscar un paciente por su cédula.
#     Implementa una búsqueda en cascada y auto-promoción de datos de forma segura.
#     """
#     try:
#         # --- PASO 1: Buscar primero en la tabla 'pacientes' ---
#         try:
#             paciente_response = supabase.table("pacientes").select("*").eq("cedula", cedula).execute()
#             if paciente_response.data and len(paciente_response.data) > 0:
#                 print(f"Paciente con cédula {cedula} encontrado directamente en 'pacientes'.")
#                 return jsonify(paciente_response.data[0])
#         except Exception as e:
#             print(f"No se encontró el paciente con cédula {cedula} en 'pacientes': {e}")

#         # --- PASO 2: Si no se encuentra, buscar en 'citas' como respaldo ---
#         print(f"Cédula {cedula} no encontrada en 'pacientes'. Buscando en 'citas'...")
#         cita_response = supabase.table("citas") \
#             .select("nombre, telefono, nombre_seguro_medico, numero_seguro_medico") \
#             .eq("cedula", cedula) \
#             .order("id", desc=True) \
#             .limit(1) \
#             .execute()

#         if cita_response.data:
#             print(f"Datos de respaldo encontrados para {cedula} en 'citas'.")
#             cita_data = cita_response.data[0]
            
#             datos_para_paciente = {
#                 "cedula": cedula,
#                 "nombre_completo": cita_data.get("nombre"),
#                 "telefono": cita_data.get("telefono"),
#                 "nombre_seguro_medico": cita_data.get("nombre_seguro_medico"),
#                 "numero_seguro_medico": cita_data.get("numero_seguro_medico")
#             }

#             # --- PASO 3 (CORREGIDO): "Promover" los datos llamando a la función RPC ---
#             try:
#                 print(f"Promoviendo datos de {cedula} a la tabla 'pacientes' vía RPC...")
                
#                 params_for_rpc = {
#                     'p_cedula': datos_para_paciente['cedula'],
#                     'p_nombre_completo': datos_para_paciente['nombre_completo'],
#                     'p_telefono': datos_para_paciente['telefono'],
#                     'p_nombre_seguro_medico': datos_para_paciente['nombre_seguro_medico'],
#                     'p_numero_seguro_medico': datos_para_paciente['numero_seguro_medico']
#                 }
                
#                 # Llama a la función de base de datos usando RPC (Remote Procedure Call)
#                 supabase.rpc('upsert_paciente_from_public', params_for_rpc).execute()
                
#                 print(f"Datos de {cedula} guardados exitosamente en 'pacientes'.")
#             except Exception as e:
#                 print(f"ADVERTENCIA: No se pudo promover al paciente {cedula}. Error RPC: {e}")

#             # Devolvemos los datos encontrados para el autocompletado.
#             return jsonify(datos_para_paciente)

#         # --- PASO 4: Si no se encuentra en ninguna tabla ---
#         print(f"No se encontraron datos para la cédula {cedula} en ninguna tabla.")
#         return jsonify({}), 404

#     except Exception as e:
#         print(f"Error CRÍTICO al buscar paciente por cédula '{cedula}': {e}")
#         return jsonify({"error": str(e)}), 500

@app.route('/api/buscar_paciente/<string:cedula>')
@public_route
def buscar_paciente(cedula):
    """
    API endpoint para buscar un paciente por su cédula.
    Implementa una búsqueda priorizando la cita más reciente para mantener los datos actualizados.
    """
    try:
        # --- PASO 1 (NUEVA LÓGICA): Buscar SIEMPRE en 'citas' para obtener los datos más recientes ---
        print(f"Buscando la cita más reciente para la cédula {cedula}...")
        cita_response = supabase.table("citas") \
            .select("nombre, telefono, nombre_seguro_medico, numero_seguro_medico") \
            .eq("cedula", cedula) \
            .order("id", desc=True) \
            .limit(1) \
            .execute()

        # --- CASO A: Se encontró una cita reciente para esta cédula ---
        if cita_response.data:
            print(f"Cita reciente encontrada para {cedula}. Sincronizando con 'pacientes'...")
            cita_data = cita_response.data[0]
            
            # Prepara los datos que se usarán para la sincronización y para devolver al frontend.
            datos_para_sincronizar = {
                "cedula": cedula,
                "nombre_completo": cita_data.get("nombre"),
                "telefono": cita_data.get("telefono"),
                "nombre_seguro_medico": cita_data.get("nombre_seguro_medico"),
                "numero_seguro_medico": cita_data.get("numero_seguro_medico")
            }

            # --- PASO 2: Usar RPC 'upsert' para crear o actualizar la tabla 'pacientes' ---
            # 'upsert' = UPDATE si existe, INSERT si no existe. Esto resuelve ambos casos.
            try:
                print(f"Ejecutando 'upsert' para el paciente {cedula} en la tabla 'pacientes'...")
                
                params_for_rpc = {
                    'p_cedula': datos_para_sincronizar['cedula'],
                    'p_nombre_completo': datos_para_sincronizar['nombre_completo'],
                    'p_telefono': datos_para_sincronizar['telefono'],
                    'p_nombre_seguro_medico': datos_para_sincronizar['nombre_seguro_medico'],
                    'p_numero_seguro_medico': datos_para_sincronizar['numero_seguro_medico']
                }
                
                supabase.rpc('upsert_paciente_from_public', params_for_rpc).execute()
                print(f"Sincronización para {cedula} completada exitosamente.")
                
            except Exception as e:
                # Si el RPC falla, es una advertencia. La app puede continuar, pero los datos no se sincronizaron.
                print(f"ADVERTENCIA: No se pudo sincronizar al paciente {cedula} vía RPC. Error: {e}")

            # Devolvemos los datos de la última cita, que son los más actualizados.
            return jsonify(datos_para_sincronizar)

        # --- CASO B: No se encontró ninguna cita, buscar en 'pacientes' como último recurso ---
        else:
            print(f"No se encontraron citas para {cedula}. Buscando directamente en 'pacientes'...")
            try:
                paciente_response = supabase.table("pacientes").select("*").eq("cedula", cedula).execute()
                if paciente_response.data:
                    print(f"Paciente {cedula} encontrado en 'pacientes' (sin citas asociadas).")
                    return jsonify(paciente_response.data[0])
            except Exception as e:
                print(f"Error al buscar en 'pacientes' para {cedula}: {e}")
                # Continuar para devolver 404

# --- PASO 3: Si no se encuentra en ninguna tabla ---
        print(f"No se encontraron datos para la cédula {cedula} en ninguna tabla.")
        return jsonify({}), 404

    except Exception as e:
        print(f"Error CRÍTICO al buscar paciente por cédula '{cedula}': {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/verificar_cita', methods=['POST'])
def api_verificar_cita():
    """API endpoint para verificar citas duplicadas desde frontend"""
    try:
        data = request.get_json()
        fecha_str = data.get('fecha')
        cedula_raw = data.get('cedula', '').strip() or None
        nombre = data.get('nombre', '').strip()
        telefono = data.get('telefono', '').strip()
        
        existe = verificar_cita_duplicada(fecha_str, cedula_raw, nombre, telefono)
        
        return jsonify({
            'exists': existe,
            'message': 'Ya existe una cita para esta fecha' if existe else 'Fecha disponible'
        })
        
    except Exception as e:
        print(f"Error en API verificar_cita: {e}")
        return jsonify({'error': str(e)}), 500

# ======================================================
# --- INICIO: RUTAS CRUD PARA GESTIÓN DE SERVICIOS ---
# ======================================================

@app.route('/admin/servicios/agregar', methods=['POST'])
@role_required('admin')
def agregar_servicio():
    nombre = request.form.get('nombre')
    precio = request.form.get('precio', 0)

    if not nombre:
        flash('❌ El nombre del servicio es obligatorio.', 'error')
        return redirect(url_for('configuracion'))
    
    try:
        supabase.table('servicios').insert({
            'nombre': nombre.strip(),
            'precio': precio
        }).execute()
        flash(f'✅ Servicio "{nombre}" agregado correctamente.', 'success')
    except APIError as e:
        # Capturamos el error específico de violación de unicidad
        if '23505' in str(e):
            flash(f'❌ Error: El servicio "{nombre}" ya existe.', 'error')
        # Capturamos el error de permisos (por si acaso)
        elif '42501' in str(e):
             flash('❌ Error de permisos de base de datos. Asegúrate de que el servidor usa la clave "service_role".', 'error')
        else:
            flash(f'❌ Error de base de datos al agregar servicio: {e}', 'error')
    except Exception as e:
        flash(f'❌ Ocurrió un error inesperado: {e}', 'error')
        
    return redirect(url_for('configuracion'))


@app.route('/admin/servicios/editar/<int:id>', methods=['POST'])
@role_required('admin')
def editar_servicio(id):
    nombre = request.form.get('nombre')
    precio = request.form.get('precio')

    if not nombre:
        flash('❌ El nombre del servicio no puede estar vacío.', 'error')
        return redirect(url_for('configuracion'))

    try:
        supabase.table('servicios').update({
            'nombre': nombre.strip(),
            'precio': precio
        }).eq('id', id).execute()
        flash(f'✅ Servicio actualizado correctamente.', 'success')
    except APIError as e:
        if '23505' in str(e):
            flash(f'❌ Error: Ya existe otro servicio con el nombre "{nombre}".', 'error')
        else:
            flash(f'❌ Error de base de datos al editar servicio: {e}', 'error')
    except Exception as e:
        flash(f'❌ Ocurrió un error inesperado al editar: {e}', 'error')
        
    return redirect(url_for('configuracion'))


@app.route('/admin/servicios/eliminar/<int:id>', methods=['POST'])
@role_required('admin')
def eliminar_servicio(id):
    try:
        supabase.table('servicios').delete().eq('id', id).execute()
        flash('🗑️ Servicio eliminado correctamente.', 'success')
    except Exception as e:
        flash(f'❌ Error al eliminar el servicio: {e}', 'error')
    
    return redirect(url_for('configuracion'))

# ======================================================
# ---    FIN: RUTAS CRUD PARA GESTIÓN DE SERVICIOS   ---
# ======================================================

# --- FUNCIÓN AUXILIAR PARA OBTENER SERVICIOS ---
def get_servicios():
    """Obtiene la lista de servicios de la BD, ordenados por nombre."""
    try:
        servicios = supabase.table("servicios").select("*").order("nombre").execute().data
        return servicios if servicios else []
    except Exception as e:
        print(f"Error al obtener la lista de servicios: {e}")
        return [] # Devuelve una lista vacía en caso de error para no romper la app

# =======================================================
# --- INICIO: FILTRO DE PLANTILLA PARA FORMATEAR FECHAS ---
# =======================================================
@app.template_filter('formatdate')
def format_date(date_string):
    """
    Filtro personalizado para convertir una fecha en formato YYYY-MM-DD
    a un formato más legible DD/MM/YYYY.
    """
    if not date_string:
        return "" # Devuelve una cadena vacía si la fecha es nula o no existe
    try:
        # 1. Convierte la cadena de texto a un objeto de fecha
        date_obj = datetime.strptime(date_string, '%Y-%m-%d')
        # 2. Formatea ese objeto al nuevo formato
        return date_obj.strftime('%d/%m/%Y')
    except (ValueError, TypeError):
        # Si hay un error (ej. formato inesperado), devuelve el valor original
        return date_string
# =======================================================
# --- FIN: FILTRO DE PLANTILLA ---
# =======================================================

def send_whatsapp_results_notification(recipient_phone, patient_name):
    """Envía una notificación de resultados listos vía WhatsApp."""
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "template",
        "template": {
            "name": "recordatorio_",  # <-- EL NOMBRE EXACTO DE TU NUEVA PLANTILLA
            "language": { "code": "es_DO" }
        }
    }
    try:
        url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        print(f"✅ Notificación de resultados enviada a {patient_name} ({recipient_phone}). Status: {response.status_code}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al enviar notificación de resultados a {patient_name} ({recipient_phone}): {e}")
        if e.response is not None:
            print("Error detallado de la API:", e.response.json())
        return False

# ==========================================================
# --- INICIO: RUTAS PARA GESTIÓN DE RESULTADOS DE PACIENTES ---
# ==========================================================

@app.route('/admin/gestion_resultados', methods=['GET', 'POST'])
@role_required('admin', 'secretaria')
def gestion_resultados():
    # --- Lógica para registrar un nuevo paciente para resultados (POST) ---
    if request.method == 'POST':
        nombre = request.form.get('nombre_completo', '').strip()
        telefono = request.form.get('telefono', '').strip()
        
        if not nombre or not telefono:
            flash('❌ El nombre y el teléfono son obligatorios.', 'error')
            return redirect(url_for('gestion_resultados'))
        
        try:
            data = {
                'cedula': request.form.get('cedula'),
                'nombre_completo': nombre,
                'telefono': telefono,
                'fecha_entrega': request.form.get('fecha_entrega') or None,
                'estudios': request.form.get('estudios')
            }
            supabase.table('resultados_pacientes').insert(data).execute()
            flash('✅ Paciente registrado para seguimiento de resultados.', 'success')
        except Exception as e:
            flash(f'❌ Error al registrar al paciente: {e}', 'error')
        
        return redirect(url_for('gestion_resultados'))

    # --- Lógica para mostrar las listas de pacientes (GET) ---
    pendientes_de_llegar = []
    listos_para_notificar = []
    ya_notificados = []
    
    try:
        response = supabase.table('resultados_pacientes').select('*').order('created_at', desc=True).execute()
        todos_los_resultados = response.data
        
        # Clasificar pacientes en las tres listas
        for r in todos_los_resultados:
            if not r.get('resultado_llego'):
                pendientes_de_llegar.append(r)
            elif not r.get('notificacion_enviada'):
                listos_para_notificar.append(r)
            else:
                ya_notificados.append(r)
                
    except Exception as e:
        flash(f'❌ Error al cargar la lista de resultados: {e}', 'error')

    return render_template(
        'gestion_resultados.html',
        pendientes=pendientes_de_llegar,
        listos=listos_para_notificar,
        notificados=ya_notificados
    )

@app.route('/admin/marcar_resultado_llegada/<int:id>', methods=['POST'])
@role_required('admin', 'secretaria')
def marcar_resultado_llegada(id):
    try:
        supabase.table('resultados_pacientes').update({'resultado_llego': True}).eq('id', id).execute()
        flash('✅ Resultado marcado como recibido.', 'success')
    except Exception as e:
        flash(f'❌ Error al actualizar el estado: {e}', 'error')
    return redirect(url_for('gestion_resultados'))

@app.route('/admin/enviar_notificaciones_resultados', methods=['POST'])
@role_required('admin', 'secretaria')
def enviar_notificaciones_resultados():
    paciente_ids = request.form.getlist('paciente_ids')
    if not paciente_ids:
        flash('⚠️ No seleccionaste ningún paciente para notificar.', 'warning')
        return redirect(url_for('gestion_resultados'))
        
    nombres_notificados = []
    errores = []

    for paciente_id in paciente_ids:
        try:
            # Obtener datos del paciente
            paciente = supabase.table('resultados_pacientes').select('*').eq('id', int(paciente_id)).single().execute().data
            if paciente:
                success = send_whatsapp_results_notification(paciente['telefono'], paciente['nombre_completo'])
                if success:
                    # Marcar como notificado en la BD
                    supabase.table('resultados_pacientes').update({'notificacion_enviada': True}).eq('id', paciente['id']).execute()
                    nombres_notificados.append(paciente['nombre_completo'])
                else:
                    errores.append(paciente['nombre_completo'])
        except Exception as e:
            print(f"Error procesando notificación para ID {paciente_id}: {e}")
            errores.append(f"ID {paciente_id} (Error interno)")

    if nombres_notificados:
        flash(f'✅ Notificaciones enviadas correctamente a {len(nombres_notificados)} pacientes.', 'success')
        # Notificación a Telegram
        mensaje_telegram = "📢 *Notificación de Resultados Enviada*\n\nSe ha notificado por WhatsApp a los siguientes pacientes:\n\n- " + "\n- ".join(nombres_notificados)
        send_telegram_message(mensaje_telegram)

    if errores:
        flash(f'❌ Hubo errores al notificar a: {", ".join(errores)}', 'error')
        
    return redirect(url_for('gestion_resultados'))

@app.route('/admin/reenviar_notificacion_resultado/<int:id>', methods=['POST'])
@role_required('admin', 'secretaria')
def reenviar_notificacion_resultado(id):
    try:
        paciente = supabase.table('resultados_pacientes').select('*').eq('id', id).single().execute().data
        if paciente:
            success = send_whatsapp_results_notification(paciente['telefono'], paciente['nombre_completo'])
            if success:
                flash(f'✅ Notificación reenviada a {paciente["nombre_completo"]}.', 'success')
                send_telegram_message(f"🔁 Notificación de resultados REENVIADA a: {paciente['nombre_completo']}")
            else:
                flash(f'❌ No se pudo reenviar la notificación a {paciente["nombre_completo"]}.', 'error')
        else:
            flash('❌ Paciente no encontrado.', 'error')
    except Exception as e:
        flash(f'❌ Error al reenviar: {e}', 'error')
    
    return redirect(url_for('gestion_resultados'))

# ==========================================================
# --- FIN: RUTAS PARA GESTIÓN DE RESULTADOS DE PACIENTES ---
# ==========================================================

# ==========================================================
# --- INICIO: RUTAS PARA GESTIÓN DE RESULTADOS DE PACIENTES - SECRETARIA ---
# ==========================================================

@app.route('/secretaria/gestion_resultados', methods=['GET', 'POST'])
@role_required('secretaria')
def secretaria_gestion_resultados():
    # --- Lógica para registrar un nuevo paciente para resultados (POST) ---
    if request.method == 'POST':
        nombre = request.form.get('nombre_completo', '').strip()
        telefono = request.form.get('telefono', '').strip()
        
        if not nombre or not telefono:
            flash('❌ El nombre y el teléfono son obligatorios.', 'error')
            return redirect(url_for('gestion_resultados'))
        
        try:
            data = {
                'cedula': request.form.get('cedula'),
                'nombre_completo': nombre,
                'telefono': telefono,
                'fecha_entrega': request.form.get('fecha_entrega') or None,
                'estudios': request.form.get('estudios')
            }
            supabase.table('resultados_pacientes').insert(data).execute()
            flash('✅ Paciente registrado para seguimiento de resultados.', 'success')
        except Exception as e:
            flash(f'❌ Error al registrar al paciente: {e}', 'error')
        
        return redirect(url_for('secretaria_gestion_resultados'))

    # --- Lógica para mostrar las listas de pacientes (GET) ---
    pendientes_de_llegar = []
    listos_para_notificar = []
    ya_notificados = []
    
    try:
        response = supabase.table('resultados_pacientes').select('*').order('created_at', desc=True).execute()
        todos_los_resultados = response.data
        
        # Clasificar pacientes en las tres listas
        for r in todos_los_resultados:
            if not r.get('resultado_llego'):
                pendientes_de_llegar.append(r)
            elif not r.get('notificacion_enviada'):
                listos_para_notificar.append(r)
            else:
                ya_notificados.append(r)
                
    except Exception as e:
        flash(f'❌ Error al cargar la lista de resultados: {e}', 'error')

    return render_template(
        'secretaria_gestion_resultados.html',
        pendientes=pendientes_de_llegar,
        listos=listos_para_notificar,
        notificados=ya_notificados
    )

@app.route('/secretaria/marcar_resultado_llegada/<int:id>', methods=['POST'])
@role_required('secretaria')
def secretaria_marcar_resultado_llegada(id):
    try:
        supabase.table('resultados_pacientes').update({'resultado_llego': True}).eq('id', id).execute()
        flash('✅ Resultado marcado como recibido.', 'success')
    except Exception as e:
        flash(f'❌ Error al actualizar el estado: {e}', 'error')
    return redirect(url_for('secretaria_gestion_resultados'))

@app.route('/secretaria/enviar_notificaciones_resultados', methods=['POST'])
@role_required('secretaria')
def secretaria_enviar_notificaciones_resultados():
    paciente_ids = request.form.getlist('paciente_ids')
    if not paciente_ids:
        flash('⚠️ No seleccionaste ningún paciente para notificar.', 'warning')
        return redirect(url_for('secretaria_gestion_resultados'))

    nombres_notificados = []
    errores = []

    for paciente_id in paciente_ids:
        try:
            # Obtener datos del paciente
            paciente = supabase.table('resultados_pacientes').select('*').eq('id', int(paciente_id)).single().execute().data
            if paciente:
                success = send_whatsapp_results_notification(paciente['telefono'], paciente['nombre_completo'])
                if success:
                    # Marcar como notificado en la BD
                    supabase.table('resultados_pacientes').update({'notificacion_enviada': True}).eq('id', paciente['id']).execute()
                    nombres_notificados.append(paciente['nombre_completo'])
                else:
                    errores.append(paciente['nombre_completo'])
        except Exception as e:
            print(f"Error procesando notificación para ID {paciente_id}: {e}")
            errores.append(f"ID {paciente_id} (Error interno)")

    if nombres_notificados:
        flash(f'✅ Notificaciones enviadas correctamente a {len(nombres_notificados)} pacientes.', 'success')
        # Notificación a Telegram
        mensaje_telegram = "📢 *Notificación de Resultados Enviada*\n\nSe ha notificado por WhatsApp a los siguientes pacientes:\n\n- " + "\n- ".join(nombres_notificados)
        send_telegram_message(mensaje_telegram)

    if errores:
        flash(f'❌ Hubo errores al notificar a: {", ".join(errores)}', 'error')
        
    return redirect(url_for('secretaria_gestion_resultados'))

@app.route('/secretaria/reenviar_notificacion_resultado/<int:id>', methods=['POST'])
@role_required('secretaria')
def secretaria_reenviar_notificacion_resultado(id):
    try:
        paciente = supabase.table('resultados_pacientes').select('*').eq('id', id).single().execute().data
        if paciente:
            success = send_whatsapp_results_notification(paciente['telefono'], paciente['nombre_completo'])
            if success:
                flash(f'✅ Notificación reenviada a {paciente["nombre_completo"]}.', 'success')
                send_telegram_message(f"🔁 Notificación de resultados REENVIADA a: {paciente['nombre_completo']}")
            else:
                flash(f'❌ No se pudo reenviar la notificación a {paciente["nombre_completo"]}.', 'error')
        else:
            flash('❌ Paciente no encontrado.', 'error')
    except Exception as e:
        flash(f'❌ Error al reenviar: {e}', 'error')
    
    return redirect(url_for('secretaria_gestion_resultados'))

# ==========================================================
# --- FIN: RUTAS PARA GESTIÓN DE RESULTADOS DE PACIENTES - SECRETARIA ---
# ==========================================================

# ==========================================================
# --- INICIO: RUTAS PARA HISTORIAL DE PACIENTES ---
# ==========================================================

@app.route('/admin/patients')
@role_required('admin', 'secretaria')
def list_patients():
    """Muestra una lista de todos los pacientes del historial. La búsqueda se maneja en el frontend."""
    # Aunque el filtrado principal es con JS, cargamos la lista completa para la página inicial.
    # El código de búsqueda se elimina del backend para simplificar, ya que JS lo manejará.
    try:
        # Siempre cargamos todos los pacientes. JavaScript se encargará de filtrar.
        response = supabase.table('patients').select('*').order('created_at', desc=True).execute()
        patients = response.data
    except Exception as e:
        flash(f'❌ Error al cargar el historial de pacientes: {e}', 'error')
        patients = []
    
    # Ya no necesitamos pasar 'search_term', el frontend se encarga de todo.
    return render_template('patients_list.html', patients=patients)


@app.route('/admin/patient/<int:patient_id>')
@role_required('admin', 'secretaria')
def patient_detail(patient_id):
    """Muestra los detalles de un paciente específico."""
    try:
        # Obtenemos los datos del paciente por su ID
        response = supabase.table('patients').select('*').eq('id', patient_id).single().execute()
        patient = response.data
        
        # Si no se encuentra el paciente, mostramos un error y redirigimos
        if not patient:
            flash('❌ Paciente no encontrado en el historial.', 'error')
            return redirect(url_for('list_patients'))
            
    except Exception as e:
        flash(f'❌ Error al buscar los detalles del paciente: {e}', 'error')
        return redirect(url_for('list_patients'))
        
    # Renderizamos la nueva plantilla de detalles
    return render_template('patient_detail.html', patient=patient)

# ==========================================================
# --- FIN: RUTAS PARA HISTORIAL DE PACIENTES ---
# ==========================================================

if __name__ == "__main__":
    app.run(debug=True)