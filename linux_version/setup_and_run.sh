#!/bin/bash
# Script de configuração e execução para Aura Access Control (Linux/Armbian)

echo "=========================================="
echo " AURA ACCESS CONTROL - SETUP LINUX/ARMBIAN"
echo "=========================================="

# 1. Instalar dependências do sistema necessárias para OpenCV no Linux
echo "[+] Instalando dependências de sistema para o OpenCV e interface gráfica..."
sudo apt-get update
sudo apt-get install -y libgl1-mesa-glx libglib2.0-0 v4l-utils python3-tk python3-pip

# Verifica se o usuário pertence ao grupo 'video' (Necessário para acessar /dev/video0)
if groups $USER | grep &>/dev/null '\bvideo\b'; then
    echo "[+] O usuário '$USER' já pertence ao grupo 'video'."
else
    echo "[!] Adicionando '$USER' ao grupo 'video'..."
    sudo usermod -aG video $USER
    echo "[!] AVISO: Você precisará reiniciar o computador ou fazer logout/login para que a permissão de vídeo seja aplicada."
fi

# 2. Configurar ambiente virtual Python (Opcional, mas recomendado)
if [ ! -d "venv" ]; then
    echo "[+] Criando ambiente virtual Python..."
    python3 -m venv venv
fi

echo "[+] Ativando ambiente virtual..."
source venv/bin/activate

# 3. Instalar dependências Python
echo "[+] Instalando dependências Python..."
pip install --upgrade pip
pip install opencv-contrib-python numpy customtkinter pillow

# 4. Checando estrutura de diretórios
echo "[+] Verificando diretórios de dados..."
mkdir -p data/faces
mkdir -p data/denied

# Verifica se o haarcascade existe
if [ ! -f "data/haarcascade_frontalface_alt.xml" ]; then
    echo "[!] Baixando classificador Haar Cascade..."
    wget -O data/haarcascade_frontalface_alt.xml https://raw.githubusercontent.com/opencv/opencv/master/data/haarcascades/haarcascade_frontalface_alt.xml
fi

echo "=========================================="
echo " Configuração Concluída!"
echo " Iniciando o sistema..."
echo "=========================================="

python3 launcher_linux.py
