import pytest
from pathlib import Path


@pytest.fixture
def sample_diff() -> str:
    return """diff --git a/src/main.py b/src/main.py
index abc123..def456 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,5 +1,7 @@
 def hello():
-    print("Hello")
+    print("Hello, world!")
+
+def new_function():
+    return True
@@ -10,3 +12,5 @@ class App:
     def run(self):
-        pass
+        self.init()
+        self.execute()
"""


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
