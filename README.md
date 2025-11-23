The integration is an fork update of previous Tado-X HACs integration custom repository
based on the below instructions, to be able to directly add it to HACs as a custom repository

https://github.com/oliviertassinari/tado-x
with this update
https://github.com/karlbeecken/ha-core/tree/tado-oauth-deviceflow/homeassistant/components/tado

it is from this thread
https://community.home-assistant.io/t/tado-integration-add-support-for-tado-x-devices/735971/253

download the contents of ha-core/homeassistant/components/tado at tado-oauth-deviceflow · karlbeecken/ha-core · GitHub and copy the tado folder over to the custom_integrations folder
on your HA installation (you can use https://download-directory.github.io/ to make downloading a single folder easier)
edit the manifest.json file in the custom_integrations/tado folder to also include a version number, for example change:
{ "domain": "tado", "name": "Tado", …
to:
{ "domain": "tado", "version": 2025.8, "name": "Tado", …
Then, your last step is to restart your HA instance. After that, you should see a “red box” icon on the tado integration
