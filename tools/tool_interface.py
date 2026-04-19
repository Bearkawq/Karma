#!/usr/bin/env python3
"""
Tool Interface - Modular Tool System

Implements a modular tool interface with:
- Declarative tool definitions
- Input schema validation
- Precondition checking
- Effect tracking
- Cost estimation
- Failure mode handling
"""

import json
import subprocess
import os
import shutil
import shlex
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime
from pathlib import Path


class Tool:
    """Base tool class with metadata and execution"""
    
    def __init__(self, name: str, definition: Dict[str, Any]):
        self.name = name
        self.definition = definition
        self.last_executed = None
        
    def execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the tool with given parameters"""
        validation = self.validate_params(params)
        if not validation['valid']:
            return {
                'success': False,
                'error': f'Parameter validation failed: {validation["errors"]}',
                'tool': self.name,
                'params': params
            }

        if not self.check_preconditions(params):
            return {
                'success': False,
                'error': 'Preconditions not met',
                'tool': self.name,
                'params': params
            }

        try:
            result = self._execute(params)
            self.last_executed = datetime.now().isoformat()
            self._track_effects(result, params)

            payload = {
                'success': True,
                'result': result,
                'tool': self.name,
                'params': params,
                'execution_time': datetime.now().isoformat()
            }
            if isinstance(result, dict) and 'success' in result:
                payload['success'] = bool(result.get('success'))
                if 'error' in result and result.get('error'):
                    payload['error'] = result.get('error')
            return payload

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'tool': self.name,
                'params': params,
                'exception': type(e).__name__
            }
    
    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate input parameters against schema"""
        errors = []
        valid = True
        
        schema = self.definition.get('parameters', {})
        
        for param_name, param_def in schema.items():
            if param_def.get('required', False) and param_name not in params:
                errors.append(f'Missing required parameter: {param_name}')
                valid = False
            elif param_name in params:
                value = params[param_name]
                expected_type = param_def.get('type', 'string')
                
                if not self._check_type(value, expected_type):
                    errors.append(f'Invalid type for {param_name}: expected {expected_type}, got {type(value).__name__}')
                    valid = False
        
        return {'valid': valid, 'errors': errors}
    
    def check_preconditions(self, params: Dict[str, Any]) -> bool:
        """Check if tool preconditions are met"""
        preconditions = self.definition.get('preconditions', [])
        
        for condition in preconditions:
            if not self._evaluate_condition(condition, params):
                return False
        
        return True
    
    def _execute(self, params: Dict[str, Any]) -> Any:
        """Actual tool execution (to be implemented by subclasses)"""
        raise NotImplementedError("Subclasses must implement _execute method")
    
    def _track_effects(self, result: Any, params: Dict[str, Any]):
        """Track tool effects"""
        # Default implementation - can be overridden
        pass
    
    def _check_type(self, value: Any, expected_type: str) -> bool:
        """Check if value matches expected type"""
        type_map = {
            'string': str,
            'number': (int, float),
            'integer': int,
            'boolean': bool,
            'array': list,
            'object': dict
        }
        
        expected = type_map.get(expected_type, str)
        if isinstance(expected, tuple):
            return isinstance(value, expected)
        return isinstance(value, expected)
    
    def _evaluate_condition(self, condition: str, params: Dict[str, Any]) -> bool:
        """Evaluate a precondition"""
        try:
            # Simple condition evaluation
            if condition == 'filesystem_available':
                return os.path.exists('/')
            elif condition == 'file_exists':
                return os.path.exists(params.get('filename', ''))
            elif condition == 'directory_exists':
                return os.path.isdir(params.get('path', ''))
            elif condition == 'network_available':
                return True  # Simple check - can be enhanced
            return True
        except Exception:
            return False
    
    def get_metadata(self) -> Dict[str, Any]:
        """Get tool metadata"""
        return {
            'name': self.name,
            'category': self.definition.get('category', 'general'),
            'description': self.definition.get('description', ''),
            'parameters': self.definition.get('parameters', {}),
            'preconditions': self.definition.get('preconditions', []),
            'effects': self.definition.get('effects', []),
            'cost': self.definition.get('cost', 1),
            'failure_modes': self.definition.get('failure_modes', []),
            'last_executed': self.last_executed
        }


class ShellTool(Tool):
    """Shell command execution tool"""
    
    def __init__(self, name: str, definition: Dict[str, Any]):
        super().__init__(name, definition)
        self.allowed_commands = definition.get('allowed_commands', [])
        self.timeout = definition.get('timeout', 30)

    def _parse_command(self, command: str) -> List[str]:
        if not isinstance(command, str) or not command.strip():
            raise ValueError('Command cannot be empty')
        if any(token in command for token in ['&&', '||', ';', '|', '>', '<']):
            raise ValueError(f'Command chaining/redirection not allowed: {command}')
        try:
            argv = shlex.split(command)
        except ValueError as e:
            raise ValueError(f'Invalid command syntax: {e}') from e
        if not argv:
            raise ValueError('Command cannot be empty')
        return argv
    
    def _execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute shell command"""
        command = params.get('command', '')
        argv = self._parse_command(command)
        executable = os.path.basename(argv[0])

        # Check if command is allowed
        if self.allowed_commands and executable not in self.allowed_commands:
            raise ValueError(f'Command not allowed: {executable}')

        # Execute command
        try:
            result = subprocess.run(
                argv,
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=True
            )

            return {
                'success': True,
                'stdout': result.stdout.strip(),
                'stderr': result.stderr.strip(),
                'returncode': result.returncode
            }

        except subprocess.TimeoutExpired:
            raise TimeoutError(f'Command timed out after {self.timeout} seconds')
        except subprocess.CalledProcessError as e:
            return {
                'success': False,
                'error': e.stderr.strip() if e.stderr else f'Command failed: {executable}',
                'stdout': e.stdout.strip() if e.stdout else '',
                'stderr': e.stderr.strip() if e.stderr else '',
                'returncode': e.returncode
            }
        except Exception as e:
            raise RuntimeError(f'Shell execution failed: {str(e)}')


class FileTool(Tool):
    """File system tool"""
    
    def __init__(self, name: str, definition: Dict[str, Any]):
        super().__init__(name, definition)
        self.max_size = definition.get('max_size', 10 * 1024 * 1024)  # 10MB default
        self.workspace_root = definition.get("workspace_root")
        raw_paths = definition.get('allowed_paths', ['~', '/tmp', '/home', '/opt'])
        self.allowed_paths = [self._normalize_allowed_path(p) for p in raw_paths]
    
    def _execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """File operation execution"""
        operation = params.get('operation')
        
        if operation == 'read':
            return self._read_file(params)
        elif operation == 'write':
            return self._write_file(params)
        elif operation == 'search':
            return self._search_files(params)
        elif operation == 'list':
            return self._list_files(params)
        else:
            raise ValueError(f'Unknown file operation: {operation}')
    
    def _read_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Read file contents"""
        path = self._resolve_path(params.get('path'))
        
        if not os.path.exists(path):
            raise FileNotFoundError(f'File not found: {path}')
        
        if os.path.getsize(path) > self.max_size:
            raise ValueError(f'File too large: {path} (>{self.max_size} bytes)')
        
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        
        return {'content': content, 'path': path, 'size': len(content)}
    
    def _write_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Write to file"""
        path = self._resolve_path(params.get('path'))
        content = params.get('content', '')
        mode = params.get('mode', 'w')
        
        # Check size
        if len(content) > self.max_size:
            raise ValueError(f'Content too large: {len(content)} bytes (>{self.max_size} bytes)')
        
        # Write file
        with open(path, mode) as f:
            f.write(content)
        
        return {'path': path, 'size': len(content), 'mode': mode}
    
    def _search_files(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Search for files"""
        path = self._resolve_path(params.get('path', '.'))
        pattern = params.get('pattern', '*')
        
        if not os.path.exists(path):
            raise FileNotFoundError(f'Path not found: {path}')
        
        import glob
        matches = sorted(glob.glob(f'{path}/{pattern}', recursive=True))

        return {'path': path, 'pattern': pattern, 'matches': matches}
    
    def _list_files(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """List directory contents"""
        path = self._resolve_path(params.get('path', '.'))
        
        if not os.path.exists(path):
            raise FileNotFoundError(f'Path not found: {path}')
        
        if not os.path.isdir(path):
            raise NotADirectoryError(f'Not a directory: {path}')
        
        entries = sorted(os.listdir(path))

        return {'path': path, 'entries': entries}
    
    def _normalize_allowed_path(self, path: str) -> str:
        expanded = os.path.expanduser(path)
        if self.workspace_root and not os.path.isabs(expanded):
            expanded = os.path.join(self.workspace_root, expanded)
        expanded = os.path.abspath(expanded)
        return os.path.normpath(expanded)

    def _resolve_path(self, path: str) -> str:
        """Resolve and validate path"""
        if not path:
            path = '.'
        expanded = os.path.expanduser(path)
        if self.workspace_root and not os.path.isabs(expanded):
            expanded = os.path.join(self.workspace_root, expanded)
        path = os.path.normpath(os.path.abspath(expanded))

        allowed = False
        for ap in self.allowed_paths:
            try:
                if os.path.commonpath([path, ap]) == ap:
                    allowed = True
                    break
            except ValueError:
                continue

        if not allowed:
            raise PermissionError(f'Path not allowed: {path}')

        return path


class SystemTool(Tool):
    """System inspection tool"""
    
    def _execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """System inspection execution"""
        operation = params.get('operation')
        
        if operation == 'info':
            return self._system_info()
        elif operation == 'disk':
            return self._disk_info()
        elif operation == 'memory':
            return self._memory_info()
        elif operation == 'cpu':
            return self._cpu_info()
        else:
            raise ValueError(f'Unknown system operation: {operation}')
    
    def _system_info(self) -> Dict[str, Any]:
        """Get system information"""
        import platform
        import sys
        
        return {
            'system': platform.system(),
            'node': platform.node(),
            'release': platform.release(),
            'version': platform.version(),
            'machine': platform.machine(),
            'processor': platform.processor(),
            'python_version': sys.version,
            'platform': platform.platform()
        }
    
    def _disk_info(self) -> Dict[str, Any]:
        """Get disk information"""
        import shutil
        
        total, used, free = shutil.disk_usage('/')
        
        return {
            'total': total,
            'used': used,
            'free': free,
            'used_percent': used / total * 100,
            'free_percent': free / total * 100
        }
    
    def _memory_info(self) -> Dict[str, Any]:
        """Get memory information"""
        try:
            import psutil
        except ImportError as e:
            raise RuntimeError('psutil is required for memory inspection') from e

        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        return {
            'total': mem.total,
            'available': mem.available,
            'used': mem.used,
            'free': mem.free,
            'percent': mem.percent,
            'swap_total': swap.total,
            'swap_used': swap.used,
            'swap_free': swap.free,
            'swap_percent': swap.percent
        }
    
    def _cpu_info(self) -> Dict[str, Any]:
        """Get CPU information"""
        try:
            import psutil
        except ImportError as e:
            raise RuntimeError('psutil is required for cpu inspection') from e

        return {
            'count': psutil.cpu_count(logical=True),
            'count_physical': psutil.cpu_count(logical=False),
            'percent': psutil.cpu_percent(interval=1),
            'percent_per_cpu': psutil.cpu_percent(interval=1, percpu=True)
        }


class CustomTool(Tool):
    """User-created bash/python script tool."""

    def __init__(self, name: str, definition: Dict[str, Any]):
        super().__init__(name, definition)
        entry = definition.get("_custom_entry", {})
        self.script_path = entry.get("path", "")
        self.lang = entry.get("lang", "bash")

    def _execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if not os.path.isfile(self.script_path):
            raise FileNotFoundError(f"Script missing: {self.script_path}")
        cmd = ["bash", self.script_path] if self.lang == "bash" else ["python3", self.script_path]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return {
            "success": r.returncode == 0,
            "error": r.stderr.strip() if r.returncode != 0 and r.stderr else (f"Custom tool failed: {self.name}" if r.returncode != 0 else ""),
            "stdout": r.stdout.strip(),
            "stderr": r.stderr.strip(),
            "returncode": r.returncode,
        }


class InvalidTool(Tool):
    """Sentinel tool for invalid tool definitions."""

    def __init__(self, name: str, definition: Dict[str, Any], error: str):
        super().__init__(name, definition)
        self._error = error

    def _execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": False, "error": self._error, "params": params}


class ToolManager:
    """Manager for multiple tools"""
    
    def __init__(self):
        self.tools = {}
        self.tool_instances = {}
    
    def register_tool(self, name: str, definition: Dict[str, Any]):
        """Register a tool definition"""
        self.tools[name] = definition
    
    def get_tool(self, name: str) -> Optional[Tool]:
        """Get a tool instance"""
        if name in self.tool_instances:
            return self.tool_instances[name]
        
        if name in self.tools:
            definition = self.tools[name]
            category = definition.get('category', 'general')

            if category == 'shell':
                tool = ShellTool(name, definition)
            elif category == 'file':
                tool = FileTool(name, definition)
            elif category == 'system':
                tool = SystemTool(name, definition)
            elif category == 'custom':
                tool = CustomTool(name, definition)
            else:
                tool = InvalidTool(name, definition, f"Unknown tool category: {category}")

            self.tool_instances[name] = tool
            return tool
        
        return None
    
    def execute_tool(self, name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a tool by name"""
        tool = self.get_tool(name)
        if not tool:
            return {'success': False, 'error': f'Tool not found: {name}'}
        
        return tool.execute(params)
    
    def get_tool_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """Get tool metadata"""
        tool = self.get_tool(name)
        return tool.get_metadata() if tool else None
    
    def list_tools(self) -> List[str]:
        """List all available tools"""
        return list(self.tools.keys())


# Example tool definitions and usage
if __name__ == "__main__":
    tm = ToolManager()
    
    # Register tools
    tm.register_tool('shell_ls', {
        'name': 'shell_ls',
        'category': 'shell',
        'description': 'List directory contents',
        'parameters': {
            'path': {'type': 'string', 'required': False},
            'all': {'type': 'boolean', 'required': False}
        },
        'preconditions': ['filesystem_available'],
        'effects': ['file_list_available'],
        'cost': 1,
        'failure_modes': ['permission_denied', 'path_not_found'],
        'allowed_commands': ['ls'],
        'timeout': 10
    })
    
    tm.register_tool('file_read', {
        'name': 'file_read',
        'category': 'file',
        'description': 'Read file contents',
        'parameters': {
            'path': {'type': 'string', 'required': True},
            'max_lines': {'type': 'integer', 'required': False}
        },
        'preconditions': ['file_exists'],
        'effects': ['file_content_available'],
        'cost': 2,
        'failure_modes': ['file_not_found', 'permission_denied'],
        'max_size': 1048576,  # 1MB
        'allowed_paths': ['~', '/tmp', '/home']
    })
    
    tm.register_tool('system_info', {
        'name': 'system_info',
        'category': 'system',
        'description': 'Get system information',
        'parameters': {},
        'preconditions': [],
        'effects': ['system_info_available'],
        'cost': 1,
        'failure_modes': []
    })
    
    # Execute tools
    print("Tool Interface Tests:")
    
    # Shell tool
    result = tm.execute_tool('shell_ls', {'command': 'ls -la', 'path': '.'})
    print(f"Shell tool result: {result}")
    
    # File tool
    result = tm.execute_tool('file_read', {'path': __file__, 'max_lines': 5})
    print(f"File tool result: {result}")
    
    # System tool
    result = tm.execute_tool('system_info', {})
    print(f"System tool result: {result}")
    
    # List tools
    print(f"Available tools: {tm.list_tools()}")
    
    # Get metadata
    metadata = tm.get_tool_metadata('shell_ls')
    print(f"Tool metadata: {metadata}")