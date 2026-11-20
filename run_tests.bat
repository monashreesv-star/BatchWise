@echo off
echo =====================================================================
echo  Running BatchWise Complete Unit Test Suite
echo =====================================================================
python -m unittest discover tests -p "test_*.py"
pause
