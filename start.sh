#!/bin/bash

# VIT Chennai AI Assistant - Startup Script
# This script starts both backend and frontend servers

# Colors for terminal output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}"
echo "╔════════════════════════════════════════════════╗"
echo "║   VIT Chennai AI Assistant - Startup Script   ║"
echo "╚════════════════════════════════════════════════╝"
echo -e "${NC}\n"

# Function to cleanup on exit
cleanup() {
    echo -e "\n${YELLOW}🛑 Shutting down servers...${NC}"
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null
        echo -e "${GREEN}✓ Backend stopped${NC}"
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null
        echo -e "${GREEN}✓ Frontend stopped${NC}"
    fi
    echo -e "${BLUE}👋 Goodbye!${NC}"
    exit 0
}

# Set trap to catch Ctrl+C
trap cleanup SIGINT SIGTERM

# Check if Backend .env exists
if [ ! -f "Backend/.env" ]; then
    echo -e "${RED}❌ Backend/.env file not found!${NC}"
    echo -e "${YELLOW}Please create Backend/.env with your API keys${NC}"
    echo -e "See SETUP_GUIDE.md for instructions"
    exit 1
fi

# Check if Frontend .env exists
if [ ! -f "Frontend/.env" ]; then
    echo -e "${YELLOW}⚠️  Frontend/.env not found, creating with default values...${NC}"
    echo "VITE_API_URL=http://localhost:8000" > Frontend/.env
    echo -e "${GREEN}✓ Created Frontend/.env${NC}"
fi

# Start Backend
echo -e "${BLUE}📡 Starting Backend Server...${NC}"
cd Backend

# Check if venv exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}Creating Python virtual environment...${NC}"
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies if needed
if ! pip list | grep -q fastapi; then
    echo -e "${YELLOW}Installing Python dependencies...${NC}"
    pip install -r ../requirements.txt
fi

# Start backend server
# Start backend server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 > ../backend.log 2>&1 &
BACKEND_PID=$!
cd ..

echo -e "${GREEN}✓ Backend starting on http://localhost:8000 (PID: $BACKEND_PID)${NC}"

# Wait for backend to be ready
echo -e "${YELLOW}⏳ Waiting for backend to start...${NC}"
sleep 3

# Check if backend is running
if curl -s http://localhost:8000/ > /dev/null; then
    echo -e "${GREEN}✓ Backend is ready!${NC}"
else
    echo -e "${RED}❌ Backend failed to start. Check backend.log for details${NC}"
    cleanup
fi

# Start Frontend
echo -e "\n${BLUE}🎨 Starting Frontend Server...${NC}"
cd Frontend

# Check if node_modules exists
if [ ! -d "node_modules" ]; then
    echo -e "${YELLOW}Installing Node dependencies...${NC}"
    if command -v bun &> /dev/null; then
        bun install
    else
        npm install
    fi
fi

# Start frontend server
if command -v bun &> /dev/null; then
    bun run dev > ../frontend.log 2>&1 &
else
    npm run dev > ../frontend.log 2>&1 &
fi
FRONTEND_PID=$!
cd ..

echo -e "${GREEN}✓ Frontend starting on http://localhost:8080 (PID: $FRONTEND_PID)${NC}"

# Display status
echo -e "\n${BLUE}╔════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           ✅ Both Servers Running!            ║${NC}"
echo -e "${BLUE}╔════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}"
echo "  🔗 Backend API:  http://localhost:8000"
echo "  🌐 Frontend UI:  http://localhost:8080"
echo -e "${NC}"
echo -e "${YELLOW}📝 Logs:${NC}"
echo "  • Backend:  backend.log"
echo "  • Frontend: frontend.log"
echo -e "\n${YELLOW}Press Ctrl+C to stop both servers${NC}\n"

# Keep script running
wait $BACKEND_PID $FRONTEND_PID
