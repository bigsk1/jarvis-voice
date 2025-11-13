┌─────────────────────────────────────────────────────────────┐
│ 1. USER → JARVIS                                            │
│    "Start the tetris server"                                │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ 2. JARVIS → OPENCODE (FULL DETAILED TASK)                   │
│    ✅ Full context, memory, preferences                     │
│    ✅ Complete task description                             │
│                                                              │
│    Example:                                                  │
│    "I need you to start the Tetris game server located at   │
│     ~/jarvis-workspace/projects/tetris-game/. The project   │
│     uses Flask and has a virtual environment. Please:       │
│     1. Navigate to the project directory                    │
│     2. Activate the venv                                    │
│     3. Start server.py in background                        │
│     4. Verify it's running on port 5000                     │
│     5. Provide me with full technical details..."           │
│                                                              │
│    ← NO CHANGES! Full detailed task sent ✅                 │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ 3. OPENCODE → JARVIS (FULL DETAILED RESPONSE)               │
│    ✅ Complete technical response                           │
│    ✅ All files created, commands run, errors encountered   │
│                                                              │
│    Example:                                                  │
│    "Task completed successfully. Here's what I did:         │
│     - Changed directory to ~/jarvis-workspace/projects/...  │
│     - Activated virtual environment at venv/bin/activate    │
│     - Verified Flask installation (version 3.0.0)           │
│     - Started server.py using nohup for background exec     │
│     - Process ID: 128712                                    │
│     - Server listening on 0.0.0.0:5000                      │
│     - Health check successful at /health endpoint           │
│     - Logs written to server.log                            │
│     Full command executed:                                  │
│     cd ~/jarvis-workspace/projects/tetris-game &&          │
│     source venv/bin/activate &&                             │
│     nohup python server.py > server.log 2>&1 &"            │
│                                                              │
│    ← NO CHANGES! Full detailed response received ✅         │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ 4. JARVIS INTERNAL PROCESSING                                │
│    ✅ Full OpenCode response stored in logs                 │
│    ✅ Complete data available for debugging                 │
│    ✅ All tool calls tracked with full details              │
│    ✅ Conversation context preserved for multi-turn         │
│                                                              │
│    ← NO CHANGES! Full context maintained ✅                 │
└─────────────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────────────┐
│ 5. JARVIS → USER (SPEECH OUTPUT)                            │
│    🎯 THIS IS WHERE CASUAL MODE APPLIES!                    │
│                                                              │
│    IF JARVIS_RESPONSE_STYLE="casual": (voice mode)          │
│       "Tetris server started successfully with PID 128712"  │
│       ← CONDENSED! Only 8 words for voice ✅                │
│                                                              │
│    IF JARVIS_RESPONSE_STYLE="detailed": (CLI mode)          │
│       "The tetris server has been successfully started!     │
│        Process ID: 128712, running on port 5000.            │
│        Server is accessible at http://192.168.70.228:5000.  │
│        Full logs available at server.log..."                │
│       ← VERBOSE! Full context for debugging ✅              │
└─────────────────────────────────────────────────────────────┘