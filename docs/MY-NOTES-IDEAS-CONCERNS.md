## My Notes, Ideas, Concerns

### Notes

- we updated memory recall to use search instead of recall -> get memory_id to be smarter wondering if this search feature can also benefit other memory tool operations, log tool,ect.. to be more acruate and use less tokens/context.

-- jarvis responds with task complete verbally in casual mode, there is no need for him to say that really. i asked him to not say it and save that to memory.

### Ideas





### Concerns

- not all jarvis-local features and tools/mcp work because a few reasons cloud uses better models and when designing and adding code / testing we focus on cloud version mostly. 

- can get costly using cloud , latest anthropic model when coding and testing, running tests over and over to troubleshoot. 


### Commands for testing

activate env 
source ~/jarvis-venv/bin/activate

test all tools
cd /home/boss/jarvis-voice/tests/integration && ./test-all-tools.sh

test all tools local
cd /home/boss/jarvis-voice/tests/integration && ./test-all-tools-local.sh

test orchestrator cloud for time
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py cloud "What time is it?"

test orchestrator local for time tool
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py local "What time is it?"

test orchestrator cloud using a specific tool send_webhook
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py cloud "use send_webhook to send a test webhook to https://n8n-roscossscggc4sogsw4s0gck.bigsk1.com/webhook/webhook-logger and short summary of the response"

test orchestrator local using a specific tool send_webhook
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py local "use send_webhook to send a test webhook to https://n8n-roscossscggc4sogsw4s0gck.bigsk1.com/webhook/webhook-logger and short summary of the response"

test orchestrator cloud using tool search_memory
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py cloud "search memory for the last webhook sent and it's url"


test opencode
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py cloud "use opencode to list files"

test opencode local
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./orchestrator/orchestrator_v2.py local "use opencode to list files"

test mcp
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./bin/test-mcp

test mcp local
cd /home/boss/jarvis-voice && source ~/jarvis-venv/bin/activate && ./bin/test-mcp --manager


### Commands for stopping tetris server
pkill -f "server.py" && echo "✅ Server stopped" || echo "No server running"


### Commands for checking if tetris server is running
lsof -i :5000 | grep LISTEN | awk '{print "✅ Flask server running on port 5000 (PID: " $2 ")"}'