*** Settings ***
Library     SSHLibrary
Suite Setup       Start the stub insights server
Suite Teardown    Tear down insights

*** Variables ***
${MID}              loki1
${STUB_PORT}        9100
${STUB_URL}         http://127.0.0.1:${STUB_PORT}
${RECORD_FILE}      /tmp/insights-stub.jsonl

# verify_tls=true vs. false is proven end-to-end against a self-signed
# server manually (verification step 6 of the plan), not here: standing up
# a self-signed HTTPS stub is more machinery than the assertion is worth in
# this suite, which only needs to prove the collector reaches the server
# and authenticates with its own subscription identity.

*** Keywords ***
Start the stub insights server
    Put File    ${CURDIR}/insights-stub.py    /tmp/insights-stub.py
    Execute Command
    ...    setsid nohup python3 /tmp/insights-stub.py ${STUB_PORT} ${RECORD_FILE} </dev/null >/tmp/insights-stub.log 2>&1 &
    Wait Until Keyword Succeeds    30s    2s    The stub insights server answers

The stub insights server answers
    ${output}    ${rc} =    Execute Command
    ...    curl -sf http://127.0.0.1:${STUB_PORT}/    return_rc=${True}
    Should Be Equal As Integers    ${rc}    0
    Should Be Equal As Strings     ${output}    ok

Tear down insights
    Execute Command    api-cli run module/${MID}/set-insights --data '{"active":false}'
    Execute Command    pkill -f insights-stub.py

Run module action
    [Arguments]    ${action}    ${data}=${EMPTY}
    IF    '${data}' == '${EMPTY}'
        ${output}    ${rc} =    Execute Command
        ...    api-cli run module/${MID}/${action}    return_rc=${True}
    ELSE
        ${output}    ${rc} =    Execute Command
        ...    api-cli run module/${MID}/${action} --data '${data}'    return_rc=${True}
    END
    Should Be Equal As Integers    ${rc}    0    action ${action} failed: ${output}
    RETURN    ${output}

The injected noise reached Loki
    ${query} =    Set Variable    {node_id=~\\".+\\"} |= \\"robot synthetic error\\"
    ${cmd} =    Catenate    SEPARATOR=${SPACE}
    ...    runagent -m ${MID} bash -c "LOKI_ADDR=http://127.0.0.1:\\$LOKI_HTTP_PORT
    ...    LOKI_USERNAME=\\$LOKI_API_AUTH_USERNAME LOKI_PASSWORD=\\$LOKI_API_AUTH_PASSWORD
    ...    logcli query --since 15m --limit 10 --forward --no-labels -q -o raw '${query}'"
    ${output}    ${rc} =    Execute Command    ${cmd}    return_rc=${True}
    Should Be Equal As Integers    ${rc}    0    logcli failed: ${output}
    Should Contain    ${output}    robot synthetic error

The stub recorded a bundle from the collector
    ${output}    ${rc} =    Execute Command    cat ${RECORD_FILE}    return_rc=${True}
    Should Be Equal As Integers    ${rc}    0    ${RECORD_FILE} was not created: ${output}
    Should Not Be Empty    ${output}
    # A non-empty, non-"unknown" system_id proves identity came from the
    # node's own subscription, not a placeholder.
    Should Match Regexp    ${output}    "system_id":\\s*"(?!unknown")[^"]+"
    Should Match Regexp    ${output}    "auth":\\s*"Basic [^"]+"
    # The digit in "error ${i}" masks to <NUM>, but the fixed prefix survives
    # in the template, so the injected noise is still recognisable here.
    Should Contain    ${output}    robot synthetic error

*** Test Cases ***
Inject synthetic noise for the window
    FOR    ${i}    IN RANGE    5
        Execute Command    logger -p daemon.err -t robot-noise robot synthetic error ${i}
    END
    Wait Until Keyword Succeeds    90s    10s    The injected noise reached Loki

Configure insights against the stub
    Run module action    set-insights
    ...    {"active":true,"base_url":"${STUB_URL}","verify_tls":false}
    ${output}    ${rc} =    Execute Command
    ...    runagent -m ${MID} systemctl --user is-active insights-collector.timer
    ...    return_rc=${True}
    Should Be Equal As Strings    ${output}    active

get-configuration reports the active collector and its stub target
    ${output} =    Run module action    get-configuration
    Should Contain    ${output}
    ...    "status": "active", "base_url": "${STUB_URL}", "verify_tls": false
    Should Contain    ${output}    "subscription_configured"

The oneshot service ships a bundle authenticated with the subscription
    ${output}    ${rc} =    Execute Command
    ...    runagent -m ${MID} systemctl --user start insights-collector.service
    ...    return_rc=${True}
    Should Be Equal As Integers    ${rc}    0    service failed to run: ${output}
    Wait Until Keyword Succeeds    60s    5s    The stub recorded a bundle from the collector

--print emits a bundle without shipping or authenticating
    ${cmd} =    Catenate    SEPARATOR=${SPACE}
    ...    runagent -m ${MID} ../bin/insights-collector --print | python3 -m json.tool
    ${output}    ${rc} =    Execute Command    ${cmd}    return_rc=${True}
    Should Be Equal As Integers    ${rc}    0    --print did not emit parseable JSON: ${output}
    Should Contain    ${output}    schema_version
    Should Contain    ${output}    templates
    Should Contain    ${output}    budget

Disabling insights stops the timer and clears the module environment
    Run module action    set-insights    {"active":false}
    ${timer}    ${rc} =    Execute Command
    ...    runagent -m ${MID} systemctl --user is-active insights-collector.timer
    ...    return_rc=${True}
    Should Not Be Equal As Strings    ${timer}    active
    # Read the environment back through the module's own API rather than
    # redis-cli, which needs credentials this suite does not carry.
    ${output} =    Run module action    get-configuration
    Should Contain    ${output}    "base_url": ""
