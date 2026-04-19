#!/usr/bin/env python3
"""
NEXUS-C GUI - Cyberpunk Terminal Interface
"""
import asyncio
import sys
import random
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import nexus_c


class SkullHead:
    """Cyberpunk stylized skull."""
    
    @staticmethod
    def get_frame(state: str, tick: int) -> str:
        """Get skull frame with glitch effects."""
        
        eye_states = {
            "idle": ["◉◉", "○○", "◐◑"],
            "thinking": ["◉◉", "◐◐", "◑◑", "◰◰"],
            "working": ["▣▣", "▤▤", "▥▥"],
            "speaking": ["◄►", "▷◁", "◀▶"],
            "sleeping": ["──", "┄┄", "┅┅"],
            "error": ["██", "▓▓", "░░"],
            "happy": ["◆◆", "◈◈", "◇◇"],
            "alert": ["⚡⚡", "█▓█", "▓▓▓"],
        }
        
        frames = eye_states.get(state, eye_states["idle"])
        idx = (tick // 3) % len(frames)
        eye = frames[idx]
        
        glitch = random.random() < 0.05
        
        skull_lines = [
            "    ╔═══════════════════════════════════╗",
            "    ║  ◈ NEXUS-C v3.9.0 ◈                ║",
            "    ╠═══════════════════════════════════╣",
            "    ║  ┌───┐    SYSTEM STATUS: ONLINE   ║",
            "    ║  │"+eye+"│    ════════════════════        ║",
            "    ║  └───┘    NEURAL CORE: ACTIVE      ║",
            "    ║  ╔═══════════════════════════════╗║",
            "    ║  ║  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ║║",
            "    ║  ║ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ ║║",
            "    ║  ║ ▓▓  ▓▓▓▓▓▓  ▓▓  ▓▓▓▓▓▓  ▓▓  ║║",
            "    ║  ║ ▓▓  ▓▓▓▓▓▓  ▓▓  ▓▓▓▓▓▓  ▓▓  ║║",
            "    ║  ║  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  ║║",
            "    ║  ╚═══════════════════════════════╝║",
            "    ║       ╔═════════════╗             ║",
            "    ║       ║ ░░░░░░░░░░░ ║             ║",
            "    ║       ╚═════════════╝             ║",
            "    ╚═══════════════════════════════════╝",
        ]
        
        if glitch:
            glitch_line = random.randint(1, len(skull_lines)-2)
            skull_lines[glitch_line] = skull_lines[glitch_line][:10] + "█" + skull_lines[glitch_line][11:]
        
        return "\n".join(skull_lines)
    
    @staticmethod
    def get_status(state: str) -> str:
        s = {
            "idle": "IDLE // AWAITING INPUT",
            "thinking": "PROCESSING DATA...",
            "working": "EXECUTING TASKS",
            "speaking": "TRANSMITTING RESPONSE",
            "sleeping": "LOW POWER MODE",
            "error": ">> SYSTEM ERROR <<",
            "happy": "TASK COMPLETE",
            "alert": "⚠ CRITICAL ALERT ⚠"
        }
        return s.get(state, "...")


class NexusGUI:
    def __init__(self):
        self.agent = None
        self.state = "idle"
        self.tick = 0
        self.messages = []
        self.running = False
        self.boot_sequence = []
    
    async def init(self):
        self.boot_sequence = [
            ">>> INITIALIZING NEXUS-C...",
            ">>> LOADING NEURAL CORES...",
            ">>> ESTABLISHING SECURE CONNECTION...",
            ">>> SYSTEM READY.",
        ]
        self.agent = nexus_c.NexusC()
    
    def render(self):
        self.tick += 1
        
        print("\033[2J\033[H", end="")
        
        state_colors = {
            "idle": "\033[36m",       # Cyan
            "thinking": "\033[35m",   # Magenta
            "working": "\033[33m",    # Yellow
            "speaking": "\033[96m",   # Light cyan
            "sleeping": "\033[94m",   # Blue
            "error": "\033[91m",       # Red
            "happy": "\033[92m",      # Green
            "alert": "\033[91m",       # Red
        }
        
        accent_color = state_colors.get(self.state, "\033[36m")
        reset = "\033[0m"
        dim = "\033[90m"
        
        print(f"{dim}╔{'═'*60}╗{reset}")
        print(f"{dim}║{reset}{accent_color}░▒▓▒░ NEXUS-C TERMINAL v3.9.0 ▒▓▒░{reset}{dim}║{reset}")
        print(f"{dim}╠{'═'*60}╣{reset}")
        
        skull = SkullHead.get_frame(self.state, self.tick)
        status = SkullHead.get_status(self.state)
        
        print(f"{dim}║{reset} {skull.replace(chr(10), reset + '\n' + dim + '║' + reset + ' ')}")
        
        status_line = f" ═══ STATUS: {status} ═══ "
        padding = (60 - len(status_line)) // 2
        print(f"{dim}║{reset}{accent_color}{' '*padding}{status_line}{' '*(60-padding-len(status_line))}{reset}{dim}║{reset}")
        
        print(f"{dim}╠{'═'*60}╣{reset}")
        print(f"{dim}║{reset} {dim}LOG:{reset}")
        
        for i, msg in enumerate(self.messages[-10:]):
            line_num = f"{i+1:03d}"
            if msg.startswith("You:"):
                print(f"{dim}║  {reset}\033[33m[{line_num}]{reset} {msg}{reset}")
            elif msg.startswith("NEXUS:"):
                print(f"{dim}║  {reset}\033[96m[{line_num}]{reset} \033[36m{msg}{reset}")
            elif msg.startswith(">>>"):
                print(f"{dim}║  {reset}\033[92m[{line_num}]{reset} {msg}{reset}")
            elif msg.startswith("Error:"):
                print(f"{dim}║  {reset}\033[91m[{line_num}]{reset} {msg}{reset}")
            else:
                print(f"{dim}║  {reset}\033[90m[{line_num}]{reset} {msg}{reset}")
        
        print(f"{dim}╠{'═'*60}╣{reset}")
        
        scan_line = "█" * (self.tick % 20 + 5)
        print(f"{dim}║ {reset}{accent_color}▌{reset}{dim} INPUT {reset}>{reset} {scan_line} {dim}▐{reset}" + " " * 20 + f"{dim}║{reset}")
        print(f"{dim}╚{'═'*60}╝{reset}")
        
        cpu = random.randint(15, 85)
        mem = random.randint(40, 70)
        print(f"\n{dim}[SYS] CPU: {cpu}% | MEM: {mem}% | TICK: {self.tick:05d} | MODE: {self.state.upper()}")
        
        print(f"{accent_color}> {reset}", end="", flush=True)
    
    async def run(self):
        await self.init()
        self.running = True
        
        for line in self.boot_sequence:
            self.messages.append(line)
            self.render()
            await asyncio.sleep(0.4)
        
        self.messages.append("")
        
        while self.running:
            self.render()
            
            try:
                user_input = input().strip()
            except EOFError:
                break
            
            if not user_input:
                continue
            
            self.messages.append(f"You: {user_input}")
            
            if user_input.lower() in [":quit", "quit", "exit"]:
                self.running = False
                print("\n\033[92m>>> SHUTTING DOWN...\033[0m")
                break
            if user_input.lower() == ":clear":
                self.messages = ["Cleared.", ""]
                continue
            if user_input.lower() == ":help":
                self.messages.extend([
                    "NEXUS-C COMMANDS:",
                    "  :quit, quit, exit - Exit the program",
                    "  :clear - Clear the message log",
                    "  :help - Show this help message",
                ])
                continue
            
            self.state = "thinking"
            self.render()
            await asyncio.sleep(0.2)
            
            try:
                result = await self.agent.run(user_input)
                self.state = "speaking"
                self.render()
                await asyncio.sleep(0.2)
                self.messages.append(f"NEXUS: {result[:200]}")
                self.state = "happy"
                self.render()
                await asyncio.sleep(0.3)
                self.state = "idle"
            except Exception as e:
                self.state = "error"
                self.messages.append(f"Error: {str(e)}")
                await asyncio.sleep(1.5)
                self.state = "idle"
        
        await self.agent.cleanup()


async def main():
    gui = NexusGUI()
    await gui.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\033[91m\n>>> INTERRUPT RECEIVED. SHUTTING DOWN...<<<\033[0m")