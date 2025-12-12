*** Settings ***
Library    SSHLibrary

*** Variables ***
${MID}            loki1

*** Test Cases ***
Check if loki service is loaded correctly
    ${output}  ${rc} =    Execute Command    runagent -m ${MID} systemctl --user show --property=LoadState loki
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}  0
    Should Be Equal As Strings    ${output}    LoadState=loaded

Check if loki-server service is loaded correctly
    ${output}  ${rc} =    Execute Command    runagent -m ${MID} systemctl --user show --property=LoadState loki-server
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}  0
    Should Be Equal As Strings    ${output}    LoadState=loaded

Check if internal traefik service is loaded correctly
    ${output}  ${rc} =    Execute Command    runagent -m ${MID} systemctl --user show --property=LoadState traefik
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}  0
    Should Be Equal As Strings    ${output}    LoadState=loaded
