import os
from flask import Flask, render_template, request, redirect, url_for, flash
from supabase import create_client, Client
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
app.secret_key = "novaglez"  # cambia por algo seguro en producción

# Configurar Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route("/", methods=["GET", "POST"])
def registrar_cita():
    if request.method == "POST":
        # Recolectar todos los datos del formulario
        nombre = request.form["nombre"]
        telefono = request.form["telefono"]
        email = "" # <-- AÑADIDO: Campo email requerido por la BD
        fecha = request.form["fecha"]
        motivo = request.form["motivo"]
        tanda = request.form["tanda"]
        numero_seguro_medico = request.form["numero_seguro_medico"] # <-- ACTUALIZADO Y AÑADIDO
        nombre_seguro_medico = request.form["nombre_seguro_medico"] # <-- AÑADIDO
        tipo_seguro_medico = request.form["tipo_seguro_medico"]   # <-- AÑADIDO

        # Crear el diccionario de datos para insertar en Supabase
        # IMPORTANTE: Las claves deben coincidir con los nombres de las columnas en la BD
        data = {
            "nombre": nombre,
            "telefono": telefono,
            "email": "", # <-- AÑADIDO
            "fecha": fecha,
            "motivo": motivo,
            "tanda": tanda,
            "numero_seguro_medico": numero_seguro_medico, # <-- AÑADIDO
            "nombre_seguro_medico": nombre_seguro_medico, # <-- AÑADIDO
            "tipo_seguro_medico": tipo_seguro_medico     # <-- AÑADIDO
        }
        
        try:
            # Insertar en Supabase
            supabase.table("citas").insert(data).execute()
            flash("✅ Cita registrada correctamente", "success")
        except Exception as e:
            # Captura cualquier error de la base de datos para depuración
            flash(f"❌ Error al registrar la cita: {e}", "error")
            print(f"Error en Supabase: {e}")

        return redirect(url_for("registrar_cita"))

    return render_template("form.html")

if __name__ == "__main__":
    app.run(debug=True)