# Navi AI Agent — MVP

An AI copilot that lets users control ERPNext through chat.
Type what you want instead of clicking through menus.

## What It Does

```
You: Create a customer named Priya Patel
Navi: ✅ Customer "Priya Patel" has been created.

You: Show me all customers
Navi: Here are your customers:
      1. Rajesh Sharma
      2. Priya Patel
      3. Grant Plastics Ltd.
      ...

You: Delete the customer Rajesh Sharma
Navi: Are you sure you want to delete customer "Rajesh Sharma"? 
      This action cannot be undone.
```

## Setup (5 minutes)

### 1. Make sure ERPNext is running
```bash
cd ~/projects/frappe_docker
docker compose -f pwd.yml up -d
```
Verify: open http://localhost:8080 in your browser

### 2. Set up the agent
```bash
cd ~/projects/navi-agent

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create your .env file
cp .env.example .env
```

### 3. Add your API key
Open the `.env` file and replace `your_anthropic_api_key_here` with your actual Anthropic API key.

```bash
nano .env
```

### 4. Run the agent
```bash
python agent.py
```

## Try These Commands

- "Show me all customers"
- "Create a customer named Amit Shah, phone 9876543210"
- "Search for customer Rajesh"
- "Create an item called Laptop with price 75000"
- "List all items"
- "Get details of customer Rajesh Sharma"
- "Delete customer Rajesh Sharma"

## Project Structure

```
navi-agent/
├── agent.py           # Main AI agent (the brain)
├── erpnext_client.py  # ERPNext API wrapper
├── requirements.txt   # Python dependencies
├── .env.example       # Template for environment variables
├── .env               # Your actual config (don't commit this)
└── README.md          # This file
```
