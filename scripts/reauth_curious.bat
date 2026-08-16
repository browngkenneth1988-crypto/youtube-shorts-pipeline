@echo off
REM Double-click to authorise the Curious Classroom channel (@CuriousClassroomTV).
REM Life With Otto keeps its own separate token — this does not touch it.
call "%~dp0reauth.bat" curious_classroom
