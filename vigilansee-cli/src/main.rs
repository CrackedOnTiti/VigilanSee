use std::env;

use color_eyre::Result;
use crossterm::event;
use ratatui::layout::{Constraint, Layout};
use ratatui::{Frame, DefaultTerminal};

fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    let mut cli_options = CliOptions::new();
    let result: Result<()>;

    cli_options.parse(&args);

    if cli_options.display_help == true {
        display_help();
        result = Ok(())
    } else {
        color_eyre::install()?;
        let terminal = ratatui::init();

        result = run(terminal);
        ratatui::restore();
        println!();
    }

    result
}

fn display_help() {
    println!("Help of vigilansee cli!!!!")
}

struct CliOptions {
    display_help: bool,
}

impl CliOptions {
    pub const fn new() -> Self {
        CliOptions { display_help: false }
    }

    pub fn parse(&mut self, args: &Vec<String>) {
        for i in 0..args.len() {
            if args[i] == "--help" || args[i] == "-h" {
                self.display_help = true
            }
        }
    }
}

/// Run the application.
fn run(mut terminal: DefaultTerminal) -> Result<()> {
    loop {
        terminal.draw(|frame| render(frame))?;
        if event::read()?.is_key_press() {
            break Ok(());
        }
    }
}

/// Render the UI.
fn render(frame: &mut Frame) {
    let layout = Layout::vertical([Constraint::Length(1), Constraint::Fill(1)]);
    let [top, bottom] = frame.area().layout(&layout);

    frame.render_widget("Powered by ratatui", top);
    frame.render_widget("Vigilansee cli", bottom);
}
