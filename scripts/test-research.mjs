import { researchPython, runPython } from "./research-python.mjs";
runPython(researchPython(), ["-m", "unittest", "discover", "-s", "apps/backend/tests/research", "-p", "test_*.py", "-v"]);
