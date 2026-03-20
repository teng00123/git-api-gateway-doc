#!/usr/bin/env python3
"""
Parse git diff output to extract API interface changes
"""
import re
import sys
import json
from typing import List, Dict, Optional

class APIDiffParser:
    def __init__(self):
        # Regex patterns for common API frameworks
        self.controller_pattern = re.compile(r'(@RestController|@Controller|@Api)")
        self.endpoint_pattern = re.compile(r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|RequestMapping)\(["\']([^"\']+)["\']')
        self.method_pattern = re.compile(r'public\s+(?:ResponseEntity<?.*?>|\w+)\s+(\w+)\s*\(')
        
    def parse_git_diff(self, diff_content: str) -> List[Dict]:
        """Parse git diff and extract API changes"""
        apis = []
        lines = diff_content.split('\n')
        
        current_file = None
        in_controller = False
        current_api = {}
        
        for line in lines:
            # Track current file
            if line.startswith('+++ b/'):
                current_file = line[6:]
                in_controller = self._is_controller_file(current_file)
                continue
                
            if not in_controller:
                continue
                
            # Look for endpoint annotations
            endpoint_match = self.endpoint_pattern.search(line)
            if endpoint_match:
                method = endpoint_match.group(1).replace('Mapping', '').upper()
                path = endpoint_match.group(2)
                current_api = {
                    'file': current_file,
                    'method': method,
                    'path': path,
                    'function': '',
                    'added': line.startswith('+')
                }
                
            # Look for function definition
            if current_api and line.strip().startswith('+') and 'public ' in line:
                method_match = self.method_pattern.search(line)
                if method_match:
                    current_api['function'] = method_match.group(1)
                    apis.append(current_api.copy())
                    
        return apis
    
    def _is_controller_file(self, filename: str) -> bool:
        """Check if file is likely a controller"""
        return any(keyword in filename.lower() 
                  for keyword in ['controller', 'api', 'rest'])
                   
    def generate_gateway_doc(self, apis: List[Dict]) -> str:
        """Generate gateway documentation in standardized format"""
        doc = []
        doc.append("# API Gateway Documentation")
        doc.append(f"Generated from git diff - {len(apis)} interfaces found\n")
        
        # Summary table
        doc.append("## Interface Summary")
        doc.append("| Method | Path | Function | File | Status |")
        doc.append("|--------|------|----------|------|--------|")
        
        for api in apis:
            status = "Added" if api.get('added', False) else "Modified"
            doc.append(f"| {api['method']} | `{api['path']}` | {api['function']} | {api['file']} | {status} |")
            
        # Detailed documentation
        doc.append("\n## Detailed Interface Documentation")
        for i, api in enumerate(apis, 1):
            doc.append(f"\n### {i}. {api['method']} {api['path']}")
            doc.append(f"- **Function**: {api['function']}")
            doc.append(f"- **File**: {api['file']}")
            doc.append(f"- **Status**: {status}")
            doc.append(f"- **Description**: [Add description here]")
            
        return "\n".join(doc)

def main():
    if len(sys.argv) != 2:
        print("Usage: python parse_git_diff.py <git_diff_file>")
        sys.exit(1)
        
    with open(sys.argv[1], 'r') as f:
        diff_content = f.read()
        
    parser = APIDiffParser()
    apis = parser.parse_git_diff(diff_content)
    documentation = parser.generate_gateway_doc(apis)
    
    # Output documentation
    print(documentation)
    
    # Save structured data
    with open('api_changes.json', 'w') as f:
        json.dump(apis, f, indent=2)
        
if __name__ == "__main__":
    main()