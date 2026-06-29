#!/bin/bash

echo "🔧 Campus Sensing Living Lab - 로컬 개발 환경 설정"
echo ""

# 1. Conda 환경 확인
if ! command -v conda &> /dev/null; then
    echo "❌ Conda가 설치되지 않았습니다. Anaconda를 설치해주세요."
    exit 1
fi
echo "✅ Conda 확인됨"

# 2. 환경 생성
ENV_NAME="livinglab"
echo ""
echo "📦 Conda 환경 생성 중... ($ENV_NAME)"
conda create -n $ENV_NAME python=3.11 -y

# 3. 환경 활성화
echo ""
echo "🚀 환경 활성화: conda activate $ENV_NAME"
source activate $ENV_NAME

# 4. 의존성 설치
echo ""
echo "📚 의존성 설치 중..."
pip install -r requirements.txt
pip install django-extensions ipython

# 5. 데이터베이스 마이그레이션
echo ""
echo "🗄️  데이터베이스 마이그레이션 중..."
export DJANGO_SETTINGS_MODULE=local_settings
python manage.py migrate

# 6. 관리자 계정 생성 (선택사항)
echo ""
echo "👤 관리자 계정 생성"
read -p "생성하시겠습니까? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python manage.py createsuperuser
fi

echo ""
echo "✨ 설정 완료!"
echo ""
echo "다음 명령어로 개발 서버를 실행하세요:"
echo "  conda activate $ENV_NAME"
echo "  export DJANGO_SETTINGS_MODULE=local_settings"
echo "  python manage.py runserver"
echo ""
echo "관리자 페이지: http://localhost:8000/admin"
echo "API 엔드포인트: http://localhost:8000/sensor/"
