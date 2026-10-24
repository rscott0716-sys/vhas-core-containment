import os
import subprocess

class VHASGitGovernor:
    def __init__(self, repo_dir):
        self.repo_dir = repo_dir

    def safe_deploy_patch(self, affected_file):
        try:
            subprocess.run(["git", "add", affected_file], cwd=self.repo_dir, check=True)
            subprocess.run(["git", "commit", "-m", f"VHAS 9.0 Autogenous Core Optimization: {affected_file}"], cwd=self.repo_dir, check=True, capture_output=True)
            subprocess.run(["git", "fetch", "origin", "main"], cwd=self.repo_dir, check=True)
            
            rebase_check = subprocess.run(["git", "rebase", "origin/main"], cwd=self.repo_dir, capture_output=True, text=True)
            if rebase_check.returncode != 0:
                self.handle_merge_conflict_isolation()
                return False

            subprocess.run(["git", "push", "origin", "main"], cwd=self.repo_dir, check=True, capture_output=True)
            return True
        except subprocess.CalledProcessError:
            return False

    def handle_merge_conflict_isolation(self):
        subprocess.run(["git", "rebase", "--abort"], cwd=self.repo_dir, capture_output=True)
        subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=self.repo_dir, capture_output=True)
