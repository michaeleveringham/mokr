import asyncio
from typing import Set

from mokr.connection import DevtoolsConnection
from mokr.constants import INPUT_INSERT_TEXT, INPUT_KEY, KEY_DEFINITIONS


class Keyboard():
    def __init__(self, client: DevtoolsConnection) -> None:
        """
        Class to allow sending key events to emulate a keyboard.

        Use `Keyboard.type("text")` to type text normally; this will dispacth
        multiple key events for each character in the given text.

        For finer control, use `Keyboard.down`, `Keyboard.up` and
        `Keyboard.send_character`.

        Special keys and modifier key can be sent. To view all key names
        and their associated event payload, use `Keyboard.key_definitions`.

        Args:
            client (DevtoolsConnection): Remote `DevtoolsConnection` instance.
        """
        self._client = client
        self._modifiers = 0
        self._pressed_keys: Set[str] = set()

    @staticmethod
    def _modifier_bit(key: str) -> int:
        if key == 'Alt':
            return 1
        if key == 'Control':
            return 2
        if key == 'Meta':
            return 4
        if key == 'Shift':
            return 8
        return 0

    @property
    def key_definitions(self) -> dict[str, dict[str, str | int]]:
        """Dictionary of key names and their corresponding event codes."""
        return KEY_DEFINITIONS

    def _key_description_from_string(self, keyString: str) -> dict:
        shift = self._modifiers & 8
        description = {
            'key': '',
            'keyCode': 0,
            'code': '',
            'text': '',
            'location': 0,
        }
        definition = KEY_DEFINITIONS.get(keyString)
        if not definition:
            raise LookupError(f'Unknown key: {keyString}')
        if 'key' in definition:
            description['key'] = definition['key']
        if shift and definition.get('shiftKey'):
            description['key'] = definition['shiftKey']
        if 'keyCode' in definition:
            description['keyCode'] = definition['keyCode']
        if shift and definition.get('shiftKeyCode'):
            description['keyCode'] = definition['shiftKeyCode']
        if 'code' in definition:
            description['code'] = definition['code']
        if 'location' in definition:
            description['location'] = definition['location']
        if len(description['key']) == 1:
            description['text'] = description['key']
        if 'text' in definition:
            description['text'] = definition['text']
        if shift and definition.get('shiftText'):
            description['text'] = definition['shiftText']
        if self._modifiers & ~8:
            description['text'] = ''
        return description

    async def down(
        self,
        key: str,
        text: str | None = None,
    ) -> None:
        """
        Send a "keyDown" event with the given `key`. Does not automatically
        send a "keyUp" event, use `Keyboard.up` for that.

        Modifier keys effect this method, meaning sending
        `Keyboard.down("shift")` and then `Keyboard.down("m")` will type an
        uppercase "M".

        Args:
            key (str): Name of key. See `Keyboard.key_definitions`.
            text (str | None, optional): Force an "input" event to be
                sent, as well. Defaults to None.
        """
        description = self._key_description_from_string(key)
        auto_repeat = description['code'] in self._pressed_keys
        self._pressed_keys.add(description['code'])
        self._modifiers |= self._modifier_bit(description['key'])
        if text is None:
            text = description['text']
        await self._client.send(
            INPUT_KEY,
            {
                'type': 'keyDown' if text else 'rawKeyDown',
                'modifiers': self._modifiers,
                'windowsVirtualKeyCode': description['keyCode'],
                'code': description['code'],
                'key': description['key'],
                'text': text,
                'unmodifiedText': text,
                'autoRepeat': auto_repeat,
                'location': description['location'],
                'isKeypad': description['location'] == 3,
            }
        )

    async def up(self, key: str) -> None:
        """
        Send a "KeyUp" event with the given `key`.

        Args:
            key (str): Name of key. See `Keyboard.key_definitions`.
            text (str | None, optional): Force an "input" event to be
                sent, as well. Defaults to None.
        """
        description = self._key_description_from_string(key)
        self._modifiers &= ~self._modifier_bit(description['key'])
        if description['code'] in self._pressed_keys:
            self._pressed_keys.remove(description['code'])
        await self._client.send(
            INPUT_KEY,
            {
                'type': 'keyUp',
                'modifiers': self._modifiers,
                'key': description['key'],
                'windowsVirtualKeyCode': description['keyCode'],
                'code': description['code'],
                'location': description['location'],
            }
        )

    async def send_character(self, char: str) -> None:
        """
        Send a character `char` into the parent `mokr.frame.Frame`. Does not
        send "keyDown" or "keyUp" event, only sends "keyPress" and "input".

        Modifier keys do not effect this method, meaning sending
        `Keyboard.down("shift")` and then `Keyboard.send_character("m")` will
        type a lowercase "m".

        Args:
            char (str): Character to send, does not accept special characters.
        """
        await self._client.send(INPUT_INSERT_TEXT, {'text': char})

    async def type_text(self, text: str, delay: int | float = 0) -> None:
        """
        Type characters into the page; whatever element is focused will receive
        the sent input.

        Note that modifier keys do not alter text case, meaning sending
        `Keyboard.down("shift")` and typing `Keyboard.type_text("mokr")`
        will not type "MOKR".

        Args:
            text (str): Text to type.
            delay (int | float, optional): Time in milliseconds to wait between
                each character typed. Defaults to 0.
        """
        for char in text:
            if char in KEY_DEFINITIONS:
                await self.press(char, delay=delay)
            else:
                await self.send_character(char)
            if delay:
                await asyncio.sleep(delay / 1000)

    async def press(self, key: str, delay: int | float | None = None) -> None:
        """
        Press the given `key` by sending `Keyboard.down` and `Keyboard.up`
        events, with the given `delay` in between.

        Modifier keys effect this method, meaning sending
        `Keyboard.down("shift")` and then `Keyboard.press("m")` will type an
        uppercase "M".

        Args:
            key (str): Name of key. See `Keyboard.key_definitions`.
            delay (int | float | None, optional): Time in milliseconds to "hold"
                the key down. Defaults to None.
        """
        await self.down(key)
        if delay is not None:
            await asyncio.sleep(delay / 1000)
        await self.up(key)
