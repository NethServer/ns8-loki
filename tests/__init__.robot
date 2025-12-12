*** Settings ***
Library           SSHLibrary
Library           DateTime

*** Variables ***
${SSH_KEYFILE}    %{HOME}/.ssh/id_ecdsa
${NODE_ADDR}      127.0.0.1
${MID}            loki1
${IMAGE_URL}      ghcr.io/nethserver/loki:latest
${JOURNAL_SINCE}  0
${SCENARIO}       install

*** Keywords ***
Connect to the node
    Open Connection   ${NODE_ADDR}
    Login With Public Key    root    ${SSH_KEYFILE}

Wait until boot completes
    ${output} =    Execute Command    systemctl is-system-running  --wait
    Should Be True    '${output}' == 'running' or '${output}' == 'degraded'

Save the journal begin timestamp
    ${tsnow} =    Get Current Date    result_format=epoch
    Set Global Variable    ${JOURNAL_SINCE}    ${tsnow}

Collect the suite journal
    Execute Command    printf "Test suite starts at %s\n" "$(date -d @${JOURNAL_SINCE})" >journal-dump.log
    Execute Command    journalctl >>journal-dump.log
    Get File    journal-dump.log    ${OUTPUT DIR}/journal-${SUITE NAME}.log

Run scenario
    Log  Scenario ${SCENARIO} with ${IMAGE_URL}  console=${True}
    IF    r'${SCENARIO}' == 'update'
        ${out}  ${rc} =  Execute Command  api-cli run update-module --data '{"force":true,"module_url":"${IMAGE_URL}","instances":["${MID}"]}'  return_rc=${True}
        Should Be Equal As Integers  ${rc}  0  action update-module ${IMAGE_URL} failed
    END


*** Settings ***
Suite Setup       Run Keywords
                  ...    Connect to the Node
                  ...    Wait until boot completes
                  ...    Save the journal begin timestamp
                  ...    Run scenario

Suite Teardown    Run Keywords
                  ...    Collect the suite journal
