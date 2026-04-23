#!/usr/bin/env python3

from demoparser2 import DemoParser
import sys




def main():
    try:
        arg = sys.argv[1]
        if arg.endswith(".dem"):
            parser = DemoParser("vigilansee-parser/dem/" + arg)
            events = parser.list_game_events()
            fields = parser.parse_player_info()
            print({"events": events, "fields": fields})
        else:
            raise ValueError()
            
    except (IndexError, ValueError):
        print("\033[0;31mExpected a \033[1;36m.dem\033[0;31m file as argument\033[0;37m")

if __name__ == "__main__":
    main()