use std::thread;
use std::time::Duration;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let path = args.next().ok_or("usage: audio-smoke <file> [seconds]")?;
    let seconds: f64 = args.next().and_then(|s| s.parse().ok()).unwrap_or(3.0);
    let engine = octobeat_audio::AudioEngine::new()?;
    if !engine.play(path, 0) {
        return Err("play command rejected".into());
    }
    let start = std::time::Instant::now();
    while start.elapsed().as_secs_f64() < seconds {
        thread::sleep(Duration::from_millis(200));
        println!(
            "pos={} dur={} playing={} slot={} underruns={}",
            engine.position(),
            engine.duration(),
            engine.is_playing() as u8,
            engine.active_slot(),
            engine.underruns()
        );
        if let Some(error) = engine.take_error() {
            eprintln!("error: {error}");
            break;
        }
    }
    engine.seek(60_000);
    thread::sleep(Duration::from_millis(800));
    println!(
        "after seek: pos={} playing={} underruns={}",
        engine.position(),
        engine.is_playing() as u8,
        engine.underruns()
    );
    engine.stop();
    thread::sleep(Duration::from_millis(200));
    Ok(())
}
