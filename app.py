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
        nombre = request.form["nombre"]
        telefono = request.form["telefono"]
        email = request.form["email"]
        fecha = request.form["fecha"]
        motivo = request.form["motivo"]
        tanda = request.form["tanda"]

        # Insertar en Supabase
        data = {
            "nombre": nombre,
            "telefono": telefono,
            "email": email,
            "fecha": fecha,
            "motivo": motivo,
            "tanda": tanda
        }
        supabase.table("citas").insert(data).execute()

        flash("✅ Cita registrada correctamente", "success")
        return redirect(url_for("registrar_cita"))

    return render_template("form.html")

if __name__ == "__main__":
    app.run(debug=True)
