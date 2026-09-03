# Insights collector Schema

```txt
http://schema.nethserver.org/loki/get-configuration.json#/properties/insights
```

State of the collector that ships deduplicated log bundles to the nethesis-insights service.

| Abstract            | Extensible | Status         | Identifiable | Custom Properties | Additional Properties | Access Restrictions | Defined In                                                                     |
| :------------------ | :--------- | :------------- | :----------- | :---------------- | :-------------------- | :------------------ | :----------------------------------------------------------------------------- |
| Can be instantiated | No         | Unknown status | No           | Forbidden         | Allowed               | none                | [get-configuration.json\*](loki/get-configuration.json "open original schema") |

## insights Type

`object` ([Insights collector](get-configuration-properties-insights-collector.md))

# insights Properties

| Property                                             | Type      | Required | Nullable       | Defined by                                                                                                                                                                                                                        |
| :--------------------------------------------------- | :-------- | :------- | :------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [status](#status)                                    | `string`  | Required | cannot be null | [Configuration of Loki](get-configuration-properties-insights-collector-properties-status.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/insights/properties/status")                                   |
| [base\_url](#base_url)                               | `string`  | Optional | cannot be null | [Configuration of Loki](get-configuration-properties-insights-collector-properties-base_url.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/insights/properties/base_url")                               |
| [verify\_tls](#verify_tls)                           | `boolean` | Optional | cannot be null | [Configuration of Loki](get-configuration-properties-insights-collector-properties-verify_tls.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/insights/properties/verify_tls")                           |
| [subscription\_configured](#subscription_configured) | `boolean` | Required | cannot be null | [Configuration of Loki](get-configuration-properties-insights-collector-properties-subscription_configured.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/insights/properties/subscription_configured") |
| [last\_run](#last_run)                               | `string`  | Optional | cannot be null | [Configuration of Loki](get-configuration-properties-insights-collector-properties-last_run.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/insights/properties/last_run")                               |

## status

State of insights-collector.service.

`status`

* is required

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-insights-collector-properties-status.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/insights/properties/status")

### status Type

`string`

### status Constraints

**enum**: the value of this property must be equal to one of the following values:

| Value        | Explanation |
| :----------- | :---------- |
| `"active"`   |             |
| `"failed"`   |             |
| `"inactive"` |             |

## base\_url

Base URL of the nethesis-insights server that receives the bundles.

`base_url`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-insights-collector-properties-base_url.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/insights/properties/base_url")

### base\_url Type

`string`

## verify\_tls

Whether the server TLS certificate is verified.

`verify_tls`

* is optional

* Type: `boolean`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-insights-collector-properties-verify_tls.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/insights/properties/verify_tls")

### verify\_tls Type

`boolean`

## subscription\_configured

True when cluster/subscription holds identity data. An enabled collector with no subscription ships nothing.

`subscription_configured`

* is required

* Type: `boolean`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-insights-collector-properties-subscription_configured.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/insights/properties/subscription_configured")

### subscription\_configured Type

`boolean`

## last\_run

Timestamp of the last successful bundle ship, empty if never run.

`last_run`

* is optional

* Type: `string`

* cannot be null

* defined in: [Configuration of Loki](get-configuration-properties-insights-collector-properties-last_run.md "http://schema.nethserver.org/loki/get-configuration.json#/properties/insights/properties/last_run")

### last\_run Type

`string`
