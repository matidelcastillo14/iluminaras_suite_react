#!/usr/bin/env bash

# Script de inicio para la versión paralela de Iluminaras Suite.
# Este script lee variables de entorno desde un archivo .env (si existe),
# configura el puerto por defecto a 5914 y arranca la aplicación Flask.

set -e

# Cargar variables de entorno desde .env si existe
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

# Asegurar que PORT esté definido (por defecto 5914 si no viene de .env)
export PORT=${PORT:-5914}

echo "Iniciando backend en el puerto ${PORT}..."

python app.py