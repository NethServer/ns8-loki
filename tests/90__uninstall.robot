*** Settings ***
Library    SSHLibrary

*** Variables ***
${MID}

*** Test Cases ***
Module removal
    [Tags]    module    remove
    ${rc} =    Execute Command    remove-module --no-preserve ${MID}
    ...    return_rc=True  return_stdout=False
    Should Be Equal As Integers    ${rc}  0
