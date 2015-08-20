#!/usr/bin/env python3

import kxg
import random
import pyglet

class World (kxg.World):
    """
    Keep track of the secret number and the range of numbers that haven't been 
    eliminated yet.
    """

    def __init__(self):
        super().__init__()
        self.number = 0
        self.lower_bound = 0
        self.upper_bound = 0
        self.winner = 0


class Referee (kxg.Referee):
    """
    Pick the secret number.
    """

    def on_start_game(self):
        self >> PickNumber(0, 5)


class PickNumber (kxg.Message):
    """
    Pick the secret number and communicate that choice to all the clients.
    """

    def __init__(self, lower_bound, upper_bound):
        self.lower_bound = lower_bound
        self.upper_bound = upper_bound
        self.number = random.randint(lower_bound + 1, upper_bound - 1)

    def on_check(self, world):
        if not self.lower_bound < self.number < self.upper_bound:
            raise kxg.MessageCheck("number out of bounds")

    def on_execute(self, world):
        world.number = self.number
        world.lower_bound = self.lower_bound
        world.upper_bound = self.upper_bound


class GuessNumber (kxg.Message):
    """
    Make a guess on behalf of the given player.  If the guess is right, that 
    player wins the game.  If the guess is wrong, the range of numbers that the 
    secret number could be is narrowed accordingly.
    """

    def __init__(self, player, guess):
        self.player = player
        self.guess = guess

    def on_check(self, world):
        pass

    def on_execute(self, world):
        if self.guess == world.number:
            world.winner = self.player
            world.end_game()

        elif self.guess < world.number:
            world.lower_bound = max(self.guess, world.lower_bound)

        elif self.guess > world.number:
            world.upper_bound = min(self.guess, world.upper_bound)


class Gui:
    """
    Manage GUI objects like the window, which exist before and after the game 
    itself.
    """

    def __init__(self):
        self.width, self.height = 600, 400
        self.window = pyglet.window.Window()
        self.window.set_size(self.width, self.height)
        self.window.set_visible(True)
        self.batch = pyglet.graphics.Batch()

    def on_refresh_gui(self):
        self.window.clear()
        self.batch.draw()


class GuiActor (kxg.Actor):
    """
    Show the players the range of numbers that haven't been eliminated yet, and 
    allow the player to guess what the number is.
    """

    def on_setup_gui(self):
        self.gui.window.set_handlers(self)

        self.guess = ''
        self.prompt = "{0.lower_bound} < {1} < {0.upper_bound}"
        self.prompt_label = pyglet.text.Label(
                "",
                color=(255, 255, 255, 255),
                font_name='Deja Vu Sans', font_size=32,
                x=self.gui.width//2, y=self.gui.height//2,
                anchor_x='center', anchor_y='center',
                batch=self.gui.batch)

    def on_draw(self):
        self.gui.on_refresh_gui()

    def on_key_press(self, symbol, modifiers):
        # If the user types a number, add that digit to the guess.

        try:
            digit = int(chr(symbol))
            self.guess += str(digit)
        except ValueError:
            pass
        
        # If the user hits backspace, remove the last digit from the guess.

        if symbol == pyglet.window.key.BACKSPACE:
            if self.guess:
                self.guess = self.guess[:-1]

        # If the user hits enter, guess the current number.

        if symbol == pyglet.window.key.ENTER:
            if self.guess:
                self >> GuessNumber(self.id, int(self.guess))
                self.guess = ''
        self.on_update_prompt()

    @kxg.subscribe_to_message(PickNumber)
    @kxg.subscribe_to_message(GuessNumber)
    def on_update_prompt(self, message=None):
        self.prompt_label.text = self.prompt.format(
                self.world, self.guess or '???')

    def on_finish_game(self):
        self.gui.window.pop_handlers()

        if self.world.winner == self.id:
            self.prompt_label.text = "You won!"
        else:
            self.prompt_label.text = "You lost!"


class AiActor (kxg.Actor):
    """
    Wait a random amount of time, then guess a random number within the 
    remaining range.
    """

    def __init__(self):
        super().__init__()
        self.reset_timer()

    def on_update_game(self, dt):
        self.timer -= dt

        if self.timer < 0:
            lower_bound = self.world.lower_bound + 1
            upper_bound = self.world.upper_bound - 1
            guess = random.randint(lower_bound, upper_bound)
            self >> GuessNumber(self.id, guess)
            self.reset_timer()

    def reset_timer(self):
        self.timer = random.uniform(1, 3)



if __name__ == '__main__':
    kxg.quickstart.main(World, Referee, Gui, GuiActor, AiActor)
