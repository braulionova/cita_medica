import os
from flask import Flask, render_template, request, redirect, session, url_for, flash
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, date  # Importamos tanto datetime como date
from queue import Queue # <-- Importa la clase Queue

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
def get_dias_llenos():
    """
    Consulta las citas, las agrupa por fecha y devuelve una lista de fechas
    que han alcanzado su límite de pacientes según la configuración.
    Solo considera fechas futuras.
    """
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
    
# --- RUTA PARA LA CONFIGURACIÓN (ACTUALIZADA) ---
@app.route("/admin/configuracion", methods=["GET", "POST"])
def configuracion():
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder", "error")
        return redirect(url_for("login"))
        
    if request.method == "POST":
        # Bloqueo de fines de semana
        sabados_bloqueados = 'true' if 'bloquear_sabados' in request.form else 'false'
        domingos_bloqueados = 'true' if 'bloquear_domingos' in request.form else 'false'
        
        # NUEVO: Límites de pacientes
        dias = ['lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado']
        config_updates = [
            {'clave': 'bloquear_sabados', 'valor': sabados_bloqueados},
            {'clave': 'bloquear_domingos', 'valor': domingos_bloqueados}
        ]
        for dia in dias:
            limite = request.form.get(f'max_pacientes_{dia}')
            # Si el campo está vacío, lo guardamos como un número alto (sin límite)
            valor_a_guardar = limite if limite else '999'
            config_updates.append({'clave': f'max_pacientes_{dia}', 'valor': valor_a_guardar})

        try:
            supabase.table('configuracion').upsert(config_updates, on_conflict='clave').execute()
            flash("✅ Configuración guardada correctamente.", "success")
        except Exception as e:
            flash(f"❌ Error al guardar la configuración: {e}", "error")
            print(f"Error al guardar config: {e}")
            
        return redirect(url_for('configuracion'))

    # Para el método GET
    config = get_configuracion()
    return render_template("configuracion.html", configuracion=config)


@app.route("/", methods=["GET", "POST"])
def registrar_cita():
    config = get_configuracion()
    
    # --- OBTENER FECHAS NO DISPONIBLES (BLOQUEADAS + LLENAS) ---
    try:
        fechas_bloqueadas_data = supabase.table("fechas_bloqueadas").select("fecha").execute().data
        fechas_bloqueadas_manualmente = {f["fecha"] for f in fechas_bloqueadas_data}
    except Exception as e:
        # ... (código de manejo de error)
        fechas_bloqueadas_manualmente = set()

    dias_llenos = set(get_dias_llenos())
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

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        usuario = request.form["usuario"]
        clave = request.form["clave"]

        # 👇 Puedes cambiar usuario y clave
        if usuario == "admin" and clave == "1234":
            session["usuario"] = usuario
            flash("✅ Bienvenido al panel de administración", "success")
            return redirect(url_for("admin"))
        else:
            flash("❌ Usuario o contraseña incorrectos", "error")
            return redirect(url_for("login"))

    return render_template("login.html")

# Logout
@app.route("/logout")
def logout():
    session.pop("usuario", None)
    flash("👋 Sesión cerrada correctamente", "success")
    return redirect(url_for("login"))

@app.route("/admin")
def admin():
    if "usuario" not in session:
        flash("⚠️ Debes iniciar sesión para acceder al panel", "error")
        return redirect(url_for("login"))

    # Obtiene el parámetro 'fecha' de la URL. Puede ser una fecha, una cadena vacía, o None.
    filtro_fecha = request.args.get("fecha")
    
    # Prepara la consulta base
    query = supabase.table("citas").select("*").order("fecha", desc=True)

    if filtro_fecha is None:
        # CASO 1: No hay parámetro 'fecha' en la URL (primera visita).
        # Usamos la fecha de hoy por defecto.
        filtro_fecha = date.today().strftime('%Y-%m-%d')
        query = query.eq("fecha", filtro_fecha)
    elif filtro_fecha:
        # CASO 2: El parámetro 'fecha' tiene un valor (no es una cadena vacía).
        # Filtramos por esa fecha.
        query = query.eq("fecha", filtro_fecha)
    # CASO 3: filtro_fecha es una cadena vacía ('').
    # No hacemos nada, por lo que la consulta base traerá todas las citas.
    
    citas = query.execute().data
    
    bloqueadas = supabase.table("fechas_bloqueadas").select("*").order("fecha", desc=True).execute().data

    # Pasamos 'filtro_fecha' a la plantilla. Será la fecha de hoy, la seleccionada, o una cadena vacía.
    return render_template("admin.html", citas=citas, bloqueadas=bloqueadas, filtro_fecha=filtro_fecha)

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

        if nueva_fecha in fechas_no_disponibles:
            flash(f"❌ No se puede mover la cita al {nueva_fecha} porque la fecha está llena o bloqueada.", "error")
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

# NUEVA RUTA: La tablet se conectará aquí para escuchar eventos
@app.route('/stream')
def stream():
    def event_stream():
        while True:
            # .get() es bloqueante: esperará hasta que haya un item en la cola
            nombre_paciente = announcement_queue.get()
            # Formato especial de Server-Sent Events: "data: <mensaje>\n\n"
            yield f"data: {nombre_paciente}\n\n"
    
    # Devolvemos una respuesta de tipo 'text/event-stream'
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
def sala_espera():
    # No requiere login, ya que es una pantalla pública
    return render_template('sala_espera.html')


if __name__ == "__main__":
    app.run(debug=True)