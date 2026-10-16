"""Reviewed Windows client contracts, matched atomically within each version.

Package profiles: four x64 official installers, SHA-256 checked against WinGet.
The 3.1.41 hotfix profile was also verified against the running native player.
Static inspection is not a claim of live acceptance on all four installations.
See docs/NETEASE_CDP_VALIDATION.md for sources and validation limits.

Never mix individual hashes from different builds: a partially changed client
must fail closed, without a protocol, window, or input fallback.
"""

RUNTIME_PROFILES: dict[str, dict[str, dict[str, str]]] = {
    "3.1.41.205529": {
        "package-c6406e5": {
            "formatter": "9b7190fad88af276224ef16f1dd365b3a3cfbcb19f26e6642ca17335e275744b",
            "normalizer": "5608ba3302bc7393d18edc1f9bfd1ce597d3bcb63699b77e0d76ae47c44cc03b",
            "replace": "31c3d7ef927b6c63268f13172121e7e37af4c1de1c3c26ddd24c1a000e20cbb1",
            "play": "148f26640c7df37ccd928b0fe9af5c21063c867a7b22c19453128b4ea9aaa2b3",
            "resume": "476eb50158bc27675619f44ed0fffeac64414bd11eda315baad6f2bbd02078ef",
            "subscribe": "7657067830eba9abb71ec9fe51d4517a0144555a44ee04db5389c736d39f68b0",
            "checkPrivilege": "381c0884e52c4f61050dc45a6e175a82ea88edc8677458f93f8a2df9559a9daf",
            "setPlaying": "f33a9c7d738b91f1ad1ae4a304f588713d3ec5b3da9d0b08f88d1e89d978199f",
            "nativePlay": "35fc09ac6caa7106f141b8c7e34cedb42a4a1f30a4285e3f9700cda84b8eea80",
        },
        "hotfix-8754fc1-1e5272a": {
            "formatter": "89e0ae1a5f9a111fbc288321a7eba4a59065d0b502f8d17199981eb52d460b5f",
            "normalizer": "5dc500cf94ee39d9d3895ad4958557556157ff1d6456a55ff4a543f6f723f278",
            "replace": "31c3d7ef927b6c63268f13172121e7e37af4c1de1c3c26ddd24c1a000e20cbb1",
            "play": "c78b8e2d6e913ad29e460af853ae0871769b5e726b124fe0bd6f56c00d4fac66",
            "resume": "3c61625435143d5f59e358ac604571b4377633fa0f0790254823cd36438ca2e0",
            "subscribe": "65d98c7a897a12c9e77f31b48602cff4ef7a1e2f89f52b5e6c4a51b24eaacf57",
            "checkPrivilege": "1da01f57cfebb991ac7e0bfc533d1d110eb9e1d5c4a3b07638a074a0d3ac39b5",
            "setPlaying": "cbe3df41372002ad7f861263037ab71c5e701e421e07ed15d298375d27043170",
            "nativePlay": "433957367c0c09d9f24e2381157a5390f1871bd4b8c9dd7e3e953dbf8704f55a",
        },
    },
    "3.1.40.205461": {
        "package-5b23b4d": {
            "formatter": "9b7190fad88af276224ef16f1dd365b3a3cfbcb19f26e6642ca17335e275744b",
            "normalizer": "2910b5a6b2a5e105e6bac40b15602ab888592dcf47743c9087631fa4f9a3036e",
            "replace": "215250a5fe92e4505abc16ecfabc84b6992d9281ea7083e95205965ac854de62",
            "play": "9921b5f12ee1815dc234bff361a3ddc51aa35e6afa6427550bc9add4a6af2e5c",
            "resume": "476eb50158bc27675619f44ed0fffeac64414bd11eda315baad6f2bbd02078ef",
            "subscribe": "d6bfa2a0fa6d64de329fc6047bc0e72f8d48d6f5c9c37824e8ba97cec99fa936",
            "checkPrivilege": "d70dd494cacfe9a8562647127c430989a14735d42ea1aed363caf9395fef40b6",
            "setPlaying": "4eb4d18e1e919ec26ebcd014d38c1584bb92a1978252a9f17ac0449f97d60583",
            "nativePlay": "01bcd7cb021a376fab24e6b67a048259f32c4329a6cb35aece5ba3ab10535882",
        }
    },
    "3.1.39.205426": {
        "package-3168567": {
            "formatter": "9b7190fad88af276224ef16f1dd365b3a3cfbcb19f26e6642ca17335e275744b",
            "normalizer": "2910b5a6b2a5e105e6bac40b15602ab888592dcf47743c9087631fa4f9a3036e",
            "replace": "056f6231478495a16cd45bc25df5b0294103589e394c49b4928467d72390b351",
            "play": "a98d7c5d22a0134f6836cfb4148b241b045048f64fa11ed2780e867c49011a7b",
            "resume": "aa9dd62fc752e5951a7a3cc7950299295b7612fdde239207eb7e065815a7cad3",
            "subscribe": "d6bfa2a0fa6d64de329fc6047bc0e72f8d48d6f5c9c37824e8ba97cec99fa936",
            "checkPrivilege": "31848a3ca3fbc17a6c01655d3f6ee225c500777daca0330e9b35a79585f77471",
            "setPlaying": "3f57df3545176ca959ecaaebc3f3e7f0dac65c877cb2952eb6a7d8a26f392be9",
            "nativePlay": "17c7157320b5b4f0e651bd1b0c3f51cbd6152b190779cf4da272346e7c73fff1",
        }
    },
    "3.1.38.205386": {
        "package-f26195c": {
            "formatter": "9b7190fad88af276224ef16f1dd365b3a3cfbcb19f26e6642ca17335e275744b",
            "normalizer": "b5a5f9491dc565bd75e2d2196728c5218c325818193e8622942c68bf6b0475fb",
            "replace": "355cb7b694d3163ae0fa46bd38885acac8b2e60e10f8a0e1af1ad27c6a8ac4d0",
            "play": "a38ebb75aa6138dce8815b9586ff175cded6591c8bfd0705c98371741639ebf7",
            "resume": "4bda91550ff6b6a321cc66e7fccbc0aaff1874d05c9a92a3250c710860523c6d",
            "subscribe": "d6bfa2a0fa6d64de329fc6047bc0e72f8d48d6f5c9c37824e8ba97cec99fa936",
            "checkPrivilege": "f2a0fde3e82b592b206420880f1c5a6fa27e18f64efe803ac0c3839ed495cebd",
            "setPlaying": "58a05a3e920f30be7941d24d4292eeaa5ba8026ae1755039453a9fb6d07bb1af",
            "nativePlay": "0ea8041dbb903aea5a50d05f37430602699c1a3dc392c9187b242fdc89b246ff",
        }
    },
}
