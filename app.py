import os
from flask import Flask, render_template, request, redirect, session, url_for, flash, Response, jsonify
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, date  # Importamos tanto datetime como date
from queue import Queue, Empty # <-- Importa la clase Queue
# 👇 AÑADIR ESTAS DOS importaciones para hashear contraseñas
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


def send_telegram_message(message):
    """Envía un mensaje al grupo de Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        response = requests.post(url, data=payload)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error al enviar mensaje a Telegram: {e}")


# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
app.secret_key = "novaglez"  # cambia por algo seguro en producción

# Configurar Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

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
    
@app.route("/admin/configuracion", methods=["GET", "POST"])
@role_required('admin')  # Solo administradores pueden acceder aquí
def configuracion():
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder", "error")
        return redirect(url_for("login"))

    # Definimos los servicios en un solo lugar para usarlos tanto en GET como en POST.
    # Esta es nuestra "única fuente de verdad" para los tipos de consulta.
    servicios = [
        ('ginecologica', 'Consulta ginecológica'),
        ('mama', 'Consulta de mama'),
        ('post', 'Post quirúrgico'),
        ('biopsia', 'Biopsia'),
        ('resultados', 'Entrega de resultados')
    ]
        
    if request.method == "POST":
        # --- Lógica existente para bloqueos y límites (sin cambios) ---
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

        # --- NUEVA LÓGICA PARA GUARDAR PRECIOS ---
        # Recorremos la lista de servicios y obtenemos el precio de cada uno desde el formulario.
        for key, _ in servicios:
            # Creamos la clave de la base de datos, ej: "precio_ginecologica"
            clave_precio = f'precio_{key}'
            # Obtenemos el valor del formulario. Si está vacío, guardamos una cadena vacía.
            valor_precio = request.form.get(clave_precio, '')
            config_updates.append({'clave': clave_precio, 'valor': valor_precio})
        
        # Guardamos todas las actualizaciones (límites, bloqueos y precios) en una sola llamada.
        try:
            supabase.table('configuracion').upsert(config_updates, on_conflict='clave').execute()
            flash("✅ Configuración guardada correctamente.", "success")
        except Exception as e:
            flash(f"❌ Error al guardar la configuración: {e}", "error")
            
        return redirect(url_for('configuracion'))

    # Para el método GET, obtenemos la configuración y la pasamos al template,
    # incluyendo ahora la lista de servicios para construir el formulario dinámicamente.
    config = get_configuracion()
    return render_template("configuracion.html", configuracion=config, servicios=servicios)


@app.route("/", methods=["GET", "POST"])
@public_route
def registrar_cita():
    config = get_configuracion()
    
    # --- OBTENER FECHAS NO DISPONIBLES (BLOQUEADAS + LLENAS) ---
    try:
        fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
        fechas_bloqueadas_manualmente = {f["fecha"] for f in fechas_bloqueadas_data}
    except Exception as e:
        # ... (código de manejo de error)
        fechas_bloqueadas_manualmente = set()

    dias_llenos = set(get_dias_llenos(config))
    # Combinamos ambas listas para pasarlas al frontend
    fechas_no_disponibles = list(fechas_bloqueadas_manualmente.union(dias_llenos))

    if request.method == "POST":
        fecha_str = request.form["fecha"]
        fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d').date()

        # VALIDACIÓN 1: Fin de semana
        if config.get('bloquear_sabados') == 'true' and fecha_obj.weekday() == 5:
            flash("❌ No se pueden agendar citas los sábados.", "error")
            return redirect(url_for("registrar_cita"))
        if config.get('bloquear_domingos') == 'true' and fecha_obj.weekday() == 6:
            flash("❌ No se pueden agendar citas los domingos.", "error")
            return redirect(url_for("registrar_cita"))
            
        # VALIDACIÓN 2: Fecha bloqueada manualmente
        if fecha_str in fechas_bloqueadas_manualmente:
            flash("❌ La fecha seleccionada no está disponible. Por favor, elija otra.", "error")
            return redirect(url_for("registrar_cita"))

        # VALIDACIÓN 3: Límite de pacientes por día
        if fecha_str in dias_llenos:
             flash("❌ El cupo para la fecha seleccionada está lleno. Por favor, elija otra.", "error")
             return redirect(url_for("registrar_cita"))
    # Traer fechas bloqueadas
    try:
        fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
        # Extraer solo las fechas en formato 'YYYY-MM-DD'
        fechas_bloqueadas = [f["fecha"] for f in fechas_bloqueadas_data]
    except Exception as e:
        print(f"Error al obtener fechas bloqueadas: {e}")
        fechas_bloqueadas = [] # Si hay un error, usa una lista vacía para no romper la página

    config = get_configuracion() # <-- Obtener configuración
    try:
        fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
        fechas_bloqueadas = [f["fecha"] for f in fechas_bloqueadas_data]
    except Exception as e:
        print(f"Error al obtener fechas bloqueadas: {e}")
        fechas_bloqueadas = []

    if request.method == "POST":
        fecha_str = request.form["fecha"]
        fecha_obj = datetime.strptime(fecha_str, '%Y-%m-%d')
        
        # --- VALIDACIÓN DE FINES DE SEMANA ---
        # weekday(): Lunes=0, Martes=1, ..., Sábado=5, Domingo=6
        if config.get('bloquear_sabados') == 'true' and fecha_obj.weekday() == 5:
            flash("❌ No se pueden agendar citas los sábados.", "error")
            return redirect(url_for("registrar_cita"))
        if config.get('bloquear_domingos') == 'true' and fecha_obj.weekday() == 6:
            flash("❌ No se pueden agendar citas los domingos.", "error")
            return redirect(url_for("registrar_cita"))
            
        if fecha_str in fechas_bloqueadas:
            flash("❌ La fecha seleccionada no está disponible. Por favor, elija otra.", "error")
            return redirect(url_for("registrar_cita"))

    if request.method == "POST":
        fecha = request.form["fecha"]
        # La validación en el backend sigue siendo crucial como medida de seguridad
        if fecha in fechas_bloqueadas:
            flash("❌ La fecha seleccionada no está disponible. Por favor, elija otra.", "error")
            return redirect(url_for("registrar_cita"))
        
        # ... (resto del código POST sin cambios)
        nombre = request.form["nombre"]
        telefono = request.form["telefono"]
        email = "" 
        motivo = request.form["motivo"]
        tanda = ""
        numero_seguro_medico = request.form["numero_seguro_medico"]
        nombre_seguro_medico = request.form["nombre_seguro_medico"]
        tipo_seguro_medico = ""

        data = {
            "nombre": nombre,
            "telefono": telefono,
            "email": "",
            "fecha": fecha,
            "motivo": motivo,
            "tanda": tanda,
            "numero_seguro_medico": numero_seguro_medico,
            "nombre_seguro_medico": nombre_seguro_medico,
            "tipo_seguro_medico": tipo_seguro_medico
        }
        
        try:
            supabase.table("citas").insert(data).execute()
            flash("✅ Cita registrada correctamente", "success")
            #enviar mensaje a telegram
            mensaje = {
                "Nombre del paciente": nombre,
                "Telefono": telefono,
                "Fecha": fecha,
                "Motivo": motivo,
                "Numero de Seguro Médico": numero_seguro_medico,
                "Nombre del seguro médico": nombre_seguro_medico
            }
            send_telegram_message("Nueva cita registrada:\n" + "\n".join([f"{k}: {v}" for k, v in mensaje.items()]))

        except Exception as e:
            flash(f"❌ Error al registrar la cita: {e}", "error")
            print(f"Error en Supabase: {e}")

        return redirect(url_for("registrar_cita"))
    
    # Si es GET, renderiza la plantilla y pasa la lista de fechas y la configuración
    config = get_configuracion()
    dias_llenos = get_dias_llenos()  # Obtiene los días que están llenos usando la función existente
    return render_template("form.html", fechas_bloqueadas=fechas_bloqueadas, dias_llenos=dias_llenos, configuracion=config)

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
        # Si ya está logueado, redirigir a su panel
        if session.get('role') == 'admin':
            return redirect(url_for('admin'))
        else:
            return redirect(url_for('secretaria_dashboard'))
        
    if request.method == "POST":
        username = request.form["usuario"]
        password = request.form["clave"]

        try:
            # Primero verificamos si hay usuarios en el sistema
            any_user = supabase.table("usuarios").select("id").execute().data
            if not any_user:
                flash("❌ No hay usuarios registrados en el sistema. Crea un administrador primero.", "error")
                return redirect(url_for("crear_admin_inicial"))

            # Buscar el usuario específico
            response = supabase.table("usuarios").select("*").eq("username", username).execute()
            users = response.data

            if not users:  # Si no se encontró el usuario
                flash("❌ Usuario o contraseña incorrectos.", "error")
                return redirect(url_for("login"))

            user_data = users[0]  # Tomamos el primer usuario que coincida
            
            if check_password_hash(user_data['password_hash'], password):
                session["usuario"] = user_data['username']
                session["role"] = user_data['role']
                
                flash(f"✅ ¡Bienvenido de nuevo, {user_data['username']}!", "success")

                # --- LÓGICA DE REDIRECCIÓN POR ROL ---
                if user_data['role'] == 'admin':
                    return redirect(url_for("admin"))
                else: # Si es 'secretaria'
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

# Eliminar cita
@app.route("/admin/eliminar_cita/<int:id>", methods=["POST"])
def eliminar_cita(id):
    supabase.table("citas").delete().eq("id", id).execute()
    flash("🗑️ Cita eliminada correctamente", "success")
    return redirect(url_for("admin"))

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

        # Actualizar la fecha en la base de datos
        try:
            supabase.table("citas").update({"fecha": nueva_fecha}).eq("id", id).execute()
            flash("✅ Cita movida correctamente a la nueva fecha.", "success")
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
            supabase.table("citas").update({"fecha": nueva_fecha}).eq("id", id).execute()
            flash("✅ Cita movida correctamente a la nueva fecha.", "success")
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

@app.route('/secretaria/pagos', methods=['GET', 'POST'])
@role_required('secretaria') # Solo secretarias pueden acceder aquí
def secretaria_registrar_pago():
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
        return redirect(url_for('registrar_pago', fecha=fecha_actual))

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
        "secretaria_pagos.html", 
        citas_por_pagar=citas_por_pagar, 
        pagos_realizados=pagos_realizados, # <- Pasamos la nueva lista
        total_pagado=total_pagado,         # <- Pasamos el nuevo total
        total_pendiente=total_pendiente,   # <- Pasamos el nuevo total
        configuracion=config,
        filtro_fecha=filtro_fecha,
        date=date,
        servicios=servicios
    )

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
        # 1. Validar fines de semana según configuración
        if config.get('bloquear_sabados') == 'true' and fecha_obj.weekday() == 5:
            flash("⚠️ La configuración actual bloquea los sábados, pero se permite el registro.", "error") # Advertencia en lugar de error
        if config.get('bloquear_domingos') == 'true' and fecha_obj.weekday() == 6:
            flash("⚠️ La configuración actual bloquea los domingos, pero se permite el registro.", "error") # Advertencia

        # 2. Validar si la fecha está bloqueada manualmente
        if fecha_str in fechas_bloqueadas:
            flash(f"❌ La fecha {fecha_str} está bloqueada manualmente y no se puede registrar la cita.", "error")
            return redirect(url_for("registrar_cita_admin"))

        # 3. SE OMITE LA VALIDACIÓN DE 'dias_llenos'. ¡Esta es la clave!

        # --- Procesar y guardar la cita (lógica existente) ---
        nombre = request.form["nombre"]
        telefono = request.form["telefono"]
        motivo = request.form["motivo"]
        numero_seguro_medico = request.form["numero_seguro_medico"]
        nombre_seguro_medico = request.form["nombre_seguro_medico"]

        data = {
            "nombre": nombre, "telefono": telefono, "fecha": fecha_str,
            "motivo": motivo, "numero_seguro_medico": numero_seguro_medico,
            "nombre_seguro_medico": nombre_seguro_medico,
            # Campos opcionales o con valores por defecto
            "email": "", "tanda": "", "tipo_seguro_medico": ""
        }
        
        try:
            supabase.table("citas").insert(data).execute()
            flash("✅ Cita registrada correctamente desde el panel de administración.", "success")
            # Opcional: Enviar notificación a Telegram
            mensaje = (f"Nueva cita registrada (Admin):\n"
                       f"Nombre: {nombre}\nTeléfono: {telefono}\nFecha: {fecha_str}\n"
                       f"Motivo: {motivo}\nSeguro: {nombre_seguro_medico} ({numero_seguro_medico})")
            send_telegram_message(mensaje)
        except Exception as e:
            flash(f"❌ Error al registrar la cita: {e}", "error")

        return redirect(url_for("registrar_cita_admin"))

    # --- LÓGICA PARA GET ---
    # Renderizamos el nuevo template. La clave es pasar una lista vacía para 'dias_llenos'.
    return render_template(
        "admin_registrar_cita.html", 
        fechas_bloqueadas=fechas_bloqueadas, 
        dias_llenos=[],  # <-- ¡AQUÍ ESTÁ LA MAGIA! El script no bloqueará ningún día por estar lleno.
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

        data = {
            "nombre": nombre, "telefono": telefono, "fecha": fecha_str,
            "motivo": motivo, "numero_seguro_medico": numero_seguro_medico,
            "nombre_seguro_medico": nombre_seguro_medico,
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


if __name__ == "__main__":
    app.run(debug=True)