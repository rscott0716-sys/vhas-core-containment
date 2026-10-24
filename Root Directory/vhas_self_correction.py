import subprocess
import json
import os

class VHASSyntaxCorrectionCore:
    def __init__(self, codebase_path):
        self.codebase_path = codebase_path
        self.max_correction_attempts = 3

    def run_pipeline_validation(self, target_file, code_patch):
        full_path = os.path.join(self.codebase_path, target_file)
        backup_path = f"{full_path}.stable"
        if os.path.exists(full_path):
            subprocess.run(["cp", full_path, backup_path])

        for attempt in range(1, self.max_correction_attempts + 1):
            with open(full_path, "w") as f:
                f.write(code_patch)
            
            result = subprocess.run(
                ["cargo", "check", "--message-format=json"],
                cwd=self.codebase_path, capture_output=True, text=True
            )
            parsed_errors = self.parse_compiler_diagnostics(result.stdout)
            
            if not parsed_errors:
                if os.path.exists(backup_path):
                    os.remove(backup_path)
                return True
            code_patch = self.generate_remediation_patch(code_patch, parsed_errors)

        subprocess.run(["mv", backup_path, full_path])
        return False

    def parse_compiler_diagnostics(self, cargo_output_json):
        error_payloads = []
        for line in cargo_output_json.splitlines():
            try:
                data = json.loads(line)
                if data.get("reason") == "compiler-message":
                    message = data.get("message", {})
                    if message.get("level") == "error":
                        error_payloads.append({
                            "code": message.get("code", {}).get("code") if message.get("code") else "SyntaxError",
                            "explanation": message.get("message"),
                            "rendered": message.get("rendered")
                        })
            except json.JSONDecodeError:
                continue
        return error_payloads

    def generate_remediation_patch(self, broken_code, errors):
        debug_package = "### RECURSIVE COMPILE ERROR DETECTED\n"
        for err in errors:
            debug_package += f"Error Type [{err['code']}]: {err['explanation']}\n{err['rendered']}\n"
        return debug_package
