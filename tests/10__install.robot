*** Settings ***
Library    SSHLibrary

*** Test Cases ***
Module installation
    ${output}  ${rc} =    Execute Command    add-module ${IMAGE_URL} 1
    ...    return_rc=True
    Should Be Equal As Integers    ${rc}  0
    &{output} =    Evaluate    ${output}
    Set Global Variable    ${MID}    ${output.module_id}

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
