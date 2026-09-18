# Electrolux Climate Component

A Home Assistant custom integration for local control of Electrolux and Kelvinator air conditioners using Broadlink-based Wi-Fi modules.

## About this fork

This repository is a fork of [jnctech/ElectroluxClimateComponent](https://github.com/jnctech/ElectroluxClimateComponent), which added support for Kelvinator models that do not expose the `sn` field expected by the original integration.

This fork focuses on improving reliability of local control, particularly around slow, missing, or delayed command responses and status updates from the appliance.

The aim is to make Home Assistant behave sensibly when communication is imperfect, without hiding real failures or losing track of the actual state reported by the air conditioner.

## Development and testing

Changes in this fork are **AI-written under maintainer guidance**.

Design decisions and test cases are guided by observed behaviour on real Kelvinator hardware, and changes are tested against physical air conditioners rather than relying only on code inspection or simulated behaviour.

Because this is reverse-engineered local control of consumer appliance firmware, behaviour may vary between models and firmware versions.
