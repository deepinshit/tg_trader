call nssm.exe install tg_trader_app "%cd%\run_tg_trader.bat"
call nssm.exe set tg_trader_app AppStdout "%cd%\logs\tg_trader_app_logs.log"
call nssm.exe set tg_trader_app AppStderr "%cd%\logs\tg_trader_app_errors.log"
call nssm set tg_trader_app AppRotateFiles 5
call nssm set tg_trader_app AppRotateOnline 1
call nssm set tg_trader_app AppRotateSeconds 86400
call nssm set tg_trader_app AppRotateBytes 1048576
call sc start tg_trader_app