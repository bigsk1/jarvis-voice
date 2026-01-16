#!/usr/bin/env python3
"""
Comprehensive status briefing tool.
Gathers data from multiple sources, creates visual report, saves to stash and canvas.
"""
import sys
import os
import json
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'lib'))
from config_loader import load_config

# Tool locations
SKILLS_DIR = os.path.join(os.path.dirname(__file__), '..')
AUTO_TOOLS_DIR = os.path.dirname(__file__)

# Timeout settings per tool type (seconds)
TIMEOUTS = {
    'default': 45,
    'weather': 60,
    'crypto_price': 45,
    'stock_price': 45,
    'generate_image': 120,
    'system_monitor': 30,
    'list_alerts': 20,
    'list_reminders': 20,
    'get_time': 10,
    'canvas': 30,
    'stash': 20,
}


def find_tool(tool_name):
    """Find tool path - check skills/ then skills/auto-tools/. Returns absolute resolved path."""
    tool_path = os.path.join(SKILLS_DIR, f"{tool_name}.py")
    if os.path.exists(tool_path):
        return os.path.abspath(os.path.realpath(tool_path))  # Resolve any .. or symlinks
    tool_path = os.path.join(AUTO_TOOLS_DIR, f"{tool_name}.py")
    if os.path.exists(tool_path):
        return os.path.abspath(os.path.realpath(tool_path))
    return None


def call_tool(tool_name, args=None):
    """Call another Jarvis tool and return its result."""
    try:
        tool_path = find_tool(tool_name)
        if not tool_path:
            return {"ok": False, "error": f"Tool {tool_name} not found"}
        
        # Get project root for proper module resolution
        project_root = os.path.join(os.path.dirname(__file__), '..', '..')
        
        input_data = json.dumps(args or {})
        timeout = TIMEOUTS.get(tool_name, TIMEOUTS['default'])
        cmd = ["python3", tool_path, input_data]
        
        # Run from project root so tools can find their lib imports
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=project_root)
        
        if result.returncode == 0 and result.stdout:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"ok": False, "error": f"Invalid JSON from {tool_name}"}
        return {"ok": False, "error": result.stderr or f"Tool {tool_name} failed"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{tool_name} timed out"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_greeting():
    """Get time-aware greeting."""
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    elif hour < 17:
        return "Good afternoon"
    return "Good evening"


def safe_get(data, *keys, default='N/A'):
    """Safely get nested dictionary values."""
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key)
        elif isinstance(data, list) and isinstance(key, int) and len(data) > key:
            data = data[key]
        else:
            return default
        if data is None:
            return default
    return data


def main():
    try:
        if len(sys.argv) > 1:
            args = json.loads(sys.argv[1])
        else:
            args = json.load(sys.stdin)
        
        load_config()
        
        # Parameters
        include_news = args.get('include_news', False)
        generate_image = args.get('generate_image', False)
        crypto_coins = args.get('crypto_coins', ['bitcoin', 'solana'])
        stock_symbols = args.get('stock_symbols', ['TSLA', 'GC=F', 'SI=F'])
        sections = args.get('sections', ['time', 'weather', 'crypto', 'stocks', 'alerts', 'reminders', 'system'])
        save_to_canvas = args.get('save_to_canvas', True)
        
        # Data collection
        report_data = {
            'generated_at': datetime.now().isoformat(),
            'greeting': get_greeting()
        }
        failures = []
        
        # 1. Time
        if 'time' in sections:
            result = call_tool('get_time')
            if result.get('ok'):
                report_data['time'] = result.get('data', {})
            else:
                failures.append(f"time: {result.get('error')}")
        
        # 2. Weather
        if 'weather' in sections:
            result = call_tool('weather', {'location': 'Hillsboro, Oregon'})
            if result.get('ok'):
                report_data['weather'] = result.get('data', {})
            else:
                failures.append(f"weather: {result.get('error')}")
        
        # 3. Crypto - extract correct fields
        if 'crypto' in sections:
            report_data['crypto'] = {}
            for coin in crypto_coins:
                result = call_tool('crypto_price', {'coin': coin})
                if result.get('ok'):
                    d = result.get('data', {})
                    price = d.get('price_usd', 0)
                    change = d.get('change_24h_percent', 0)
                    name = d.get('coin', coin.title())
                    
                    # Pre-format display string so LLM doesn't mangle it
                    change_str = f"+{change:.1f}%" if change >= 0 else f"{change:.1f}%"
                    if price >= 1000:
                        price_display = f"${int(price):,}"  # "$93,362"
                    else:
                        price_display = f"${price:.2f}"
                    
                    report_data['crypto'][coin] = {
                        'price': price,
                        'price_display': price_display,  # Pre-formatted: "$93,362"
                        'change_24h': change,
                        'change_display': change_str,  # Pre-formatted: "+1.4%"
                        'summary': f"{name} {price_display} ({change_str})",  # "Bitcoin $93,362 (+1.4%)"
                        'market_cap': d.get('market_cap_usd', 0),
                        'name': name
                    }
                else:
                    failures.append(f"crypto_{coin}: {result.get('error')}")
        
        # 3b. Stocks - extract correct fields
        if 'stocks' in sections:
            report_data['stocks'] = {}
            for symbol in stock_symbols:
                result = call_tool('stock_price', {'symbol': symbol})
                if result.get('ok'):
                    d = result.get('data', {})
                    price = d.get('price_usd', 0)
                    change = d.get('change_today_percent', 0)
                    name = d.get('company', symbol.upper())
                    ticker = d.get('symbol', symbol.upper())
                    
                    # Pre-format display string so LLM doesn't mangle it
                    change_str = f"+{change:.1f}%" if change >= 0 else f"{change:.1f}%"
                    if price >= 1000:
                        price_display = f"${int(price):,}"
                    else:
                        price_display = f"${price:.2f}"
                    
                    report_data['stocks'][ticker] = {
                        'price': price,
                        'price_display': price_display,
                        'change_today': change,
                        'change_display': change_str,
                        'summary': f"{ticker} {price_display} ({change_str})",
                        'company': name,
                        'market_cap': d.get('market_cap_usd', 0),
                        'market_cap_display': d.get('market_cap_display'),
                        'pe_ratio': d.get('pe_ratio'),
                        'sector': d.get('sector'),
                    }
                else:
                    failures.append(f"stock_{symbol}: {result.get('error')}")
        
        # 4. Alerts - pending only
        if 'alerts' in sections:
            result = call_tool('list_alerts', {'status': 'pending'})
            if result.get('ok'):
                report_data['alerts'] = result.get('data', {})
            else:
                failures.append(f"alerts: {result.get('error')}")
        
        # 5. Reminders - scheduled only (not acknowledged/triggered)
        if 'reminders' in sections:
            result = call_tool('list_reminders', {'status': 'scheduled', 'limit': 10})
            if result.get('ok'):
                report_data['reminders'] = result.get('data', {})
            else:
                failures.append(f"reminders: {result.get('error')}")
        
        # 6. System - extract key metrics
        if 'system' in sections:
            result = call_tool('system_monitor')
            if result.get('ok'):
                d = result.get('data', {})
                # Get main disk (usually the first real one, skip loop devices)
                disks = d.get('disks', [])
                main_disk = next((disk for disk in disks if not disk.get('device', '').startswith('/dev/loop')), disks[0] if disks else {})
                
                report_data['system'] = {
                    'cpu_percent': safe_get(d, 'cpu', 'total_percent', default=0),
                    'memory_percent': safe_get(d, 'memory', 'ram', 'percent_used', default=0),
                    'memory_used_gb': safe_get(d, 'memory', 'ram', 'used_gb', default=0),
                    'memory_total_gb': safe_get(d, 'memory', 'ram', 'total_gb', default=0),
                    'disk_percent': main_disk.get('percent_used', 0),
                    'disk_used_gb': main_disk.get('used_gb', 0),
                    'disk_total_gb': main_disk.get('total_gb', 0),
                    'disk_mount': main_disk.get('mountpoint', '/'),
                    'uptime': safe_get(d, 'uptime', 'uptime_string', default='N/A'),
                    'network_sent_gb': safe_get(d, 'network', 'bytes_sent_gb', default=0),
                    'network_recv_gb': safe_get(d, 'network', 'bytes_recv_gb', default=0),
                }
            else:
                failures.append(f"system: {result.get('error')}")
        
        # News flag
        if include_news:
            report_data['news_requested'] = True
        
        report_data['failures'] = failures
        
        # Generate image if requested - include actual data for Gemini to render
        image_stash_ref = None
        if generate_image:
            # Build detailed prompt with actual values
            prompt_parts = ["Create a modern forward facing status dashboard display showing:"]
            
            # Weather with actual data
            if 'weather' in report_data:
                w = report_data['weather']
                temp = w.get('temperature', 'N/A')
                cond = w.get('condition', 'clear')
                humidity = w.get('humidity', 'N/A')
                prompt_parts.append(f"WEATHER: {temp}°F, {cond}, {humidity}% humidity")
            
            # Crypto with actual prices and changes
            if report_data.get('crypto'):
                crypto_lines = []
                for coin, data in report_data['crypto'].items():
                    price = data.get('price', 0)
                    change = data.get('change_24h', 0)
                    arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
                    crypto_lines.append(f"{data.get('name', coin)}: ${price:,.0f} ({arrow}{abs(change):.1f}%)")
                prompt_parts.append(f"CRYPTO: {', '.join(crypto_lines)}")
            
            # Stocks with actual prices and changes
            if report_data.get('stocks'):
                stock_lines = []
                for ticker, data in report_data['stocks'].items():
                    price = data.get('price', 0)
                    change = data.get('change_today', 0)
                    arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
                    stock_lines.append(f"{ticker}: ${price:,.2f} ({arrow}{abs(change):.1f}%)")
                prompt_parts.append(f"STOCKS: {', '.join(stock_lines)}")
            
            # System stats with actual numbers
            if 'system' in report_data:
                s = report_data['system']
                prompt_parts.append(f"SYSTEM: CPU {s.get('cpu_percent', 0):.0f}%, RAM {s.get('memory_percent', 0):.0f}%, Disk {s.get('disk_percent', 0):.0f}%")
                prompt_parts.append(f"Uptime: {s.get('uptime', 'N/A')}")
            
            # Reminders/alerts count
            alert_count = len(report_data.get('alerts', {}).get('alerts', []))
            reminder_count = len(report_data.get('reminders', {}).get('reminders', []))
            prompt_parts.append(f"ALERTS: {alert_count}, REMINDERS: {reminder_count}")
            
            # Style instructions
            prompt_parts.append("Style: Dark theme dashboard with neon accents, clean typography showing all values clearly, futuristic HUD design, glowing elements")
            
            image_prompt = ". ".join(prompt_parts)
            
            img_result = call_tool('generate_image', {'prompt': image_prompt, 'aspect_ratio': 'landscape'})
            if img_result.get('ok'):
                # stash_ref is inside data.saved.stash_ref
                image_stash_ref = safe_get(img_result, 'data', 'saved', 'stash_ref', default=None)
            else:
                failures.append(f"image: {img_result.get('error', 'failed')}")
        
        # Save report to stash
        stash_result = call_tool('stash', {
            'action': 'save',
            'kind': 'json',
            'json': report_data,
            'name': f"status_recap_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            'tags': ['status', 'recap']
        })
        stash_ref = stash_result.get('data', {}).get('ref') if stash_result.get('ok') else None
        
        # Build speech summary
        speech_parts = [report_data['greeting']]
        
        # Time
        now = datetime.now()
        speech_parts.append(f"It's {now.strftime('%I:%M %p')} {now.strftime('%A')}")
        
        # Weather
        if 'weather' in report_data:
            w = report_data['weather']
            temp = w.get('temperature', w.get('temp'))
            cond = w.get('condition', '')
            if temp:
                speech_parts.append(f"{temp}°F with {cond}" if cond else f"{temp}°F")
        
        # Crypto - use pre-formatted summary
        crypto_summaries = [data.get('summary') for data in report_data.get('crypto', {}).values() if data.get('summary')]
        if crypto_summaries:
            speech_parts.append(", ".join(crypto_summaries))
        
        # Stocks - use pre-formatted summary
        stock_summaries = [data.get('summary') for data in report_data.get('stocks', {}).values() if data.get('summary')]
        if stock_summaries:
            speech_parts.append(", ".join(stock_summaries))
        
        # Alerts/reminders counts
        alert_count = len(report_data.get('alerts', {}).get('alerts', []))
        reminder_count = len(report_data.get('reminders', {}).get('reminders', []))
        if alert_count:
            speech_parts.append(f"{alert_count} active alert{'s' if alert_count > 1 else ''}")
        else:
            speech_parts.append("No alerts")
        if reminder_count:
            speech_parts.append(f"{reminder_count} upcoming reminder{'s' if reminder_count > 1 else ''}")
        
        # System warnings
        sys_data = report_data.get('system', {})
        if sys_data.get('cpu_percent', 0) > 80:
            speech_parts.append(f"Warning: CPU at {sys_data['cpu_percent']:.0f}%")
        if sys_data.get('disk_percent', 0) > 85:
            speech_parts.append(f"Warning: Disk at {sys_data['disk_percent']:.0f}%")
        
        if failures:
            speech_parts.append(f"{len(failures)} data source{'s' if len(failures) > 1 else ''} unavailable")
        
        speech = ". ".join(speech_parts) + ". Full details on canvas."
        
        # Build executive summary for canvas
        summary_parts = []
        
        # Weather summary
        if 'weather' in report_data:
            w = report_data['weather']
            temp = w.get('temperature', 'N/A')
            cond = w.get('condition', 'N/A')
            humidity = w.get('humidity', 'N/A')
            summary_parts.append(f"**{temp}°F** with {cond} ({humidity}% humidity)")
        
        # Crypto summary - use pre-formatted values
        crypto_summaries = []
        for coin, data in report_data.get('crypto', {}).items():
            change = data.get('change_24h', 0)
            emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
            price_display = data.get('price_display', f"${data.get('price', 0):,.0f}")
            change_display = data.get('change_display', f"{change:+.1f}%")
            name = data.get('name', coin.title())
            crypto_summaries.append(f"{name} **{price_display}** ({emoji} {change_display})")
        if crypto_summaries:
            summary_parts.append(" • ".join(crypto_summaries))
        
        # Stock summary - use pre-formatted values
        stock_summaries = []
        for ticker, data in report_data.get('stocks', {}).items():
            change = data.get('change_today', 0)
            emoji = "📈" if change > 0 else "📉" if change < 0 else "➡️"
            price_display = data.get('price_display', f"${data.get('price', 0):,.2f}")
            change_display = data.get('change_display', f"{change:+.1f}%")
            stock_summaries.append(f"{ticker} **{price_display}** ({emoji} {change_display})")
        if stock_summaries:
            summary_parts.append(" • ".join(stock_summaries))
        
        # Alerts/reminders summary
        alert_count = len(report_data.get('alerts', {}).get('alerts', []))
        reminder_count = len(report_data.get('reminders', {}).get('reminders', []))
        status_items = []
        if alert_count:
            status_items.append(f"**{alert_count}** active alert{'s' if alert_count > 1 else ''}")
        else:
            status_items.append("✅ No alerts")
        if reminder_count:
            status_items.append(f"**{reminder_count}** upcoming reminder{'s' if reminder_count > 1 else ''}")
        else:
            status_items.append("No reminders")
        summary_parts.append(" • ".join(status_items))
        
        # System summary
        if 'system' in report_data:
            s = report_data['system']
            cpu = s.get('cpu_percent', 0)
            mem = s.get('memory_percent', 0)
            disk = s.get('disk_percent', 0)
            uptime = s.get('uptime', 'N/A')
            # Add warning emoji if any metric is high
            cpu_str = f"🔴 CPU {cpu:.0f}%" if cpu > 80 else f"CPU {cpu:.0f}%"
            disk_str = f"🔴 Disk {disk:.0f}%" if disk > 85 else f"Disk {disk:.0f}%"
            summary_parts.append(f"System: {cpu_str}, RAM {mem:.0f}%, {disk_str} • Uptime: {uptime}")
        
        executive_summary = ". ".join(summary_parts)
        
        # Build canvas content
        canvas_lines = [
            f"# Status Recap",
            f"**{now.strftime('%A, %B %d, %Y at %I:%M %p')}**",
            "",
            f"> {report_data['greeting']}! {executive_summary}",
            ""
        ]
        
        # Image at top if generated
        if image_stash_ref:
            canvas_lines.insert(0, f"![Status Dashboard]({image_stash_ref})")
            canvas_lines.insert(1, "")
        
        canvas_lines.append("---")
        canvas_lines.append("")
        
        # Weather section
        if 'weather' in report_data:
            w = report_data['weather']
            canvas_lines.extend([
                "## 🌤️ Weather (Hillsboro, OR)",
                f"- **Condition:** {w.get('condition', 'N/A')}",
                f"- **Temperature:** {w.get('temperature', 'N/A')}°F (feels like {w.get('feels_like', 'N/A')}°F)",
                f"- **Humidity:** {w.get('humidity', 'N/A')}%",
                f"- **Wind:** {w.get('wind_speed', 'N/A')} {w.get('wind_unit', 'mph')}",
                ""
            ])
        
        # Crypto section
        if report_data.get('crypto'):
            canvas_lines.append("## 📈 Cryptocurrency")
            for coin, data in report_data['crypto'].items():
                price = data.get('price', 0)
                change = data.get('change_24h', 0)
                emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
                canvas_lines.append(f"- **{data.get('name', coin.upper())}:** ${price:,.2f} ({emoji} {change:+.2f}% 24h)")
            canvas_lines.append("")
        
        # Stocks section
        if report_data.get('stocks'):
            canvas_lines.append("## 📊 Stocks")
            for ticker, data in report_data['stocks'].items():
                price = data.get('price', 0)
                change = data.get('change_today', 0)
                emoji = "🟢" if change > 0 else "🔴" if change < 0 else "⚪"
                company = data.get('company', ticker)
                pe = data.get('pe_ratio')
                cap = data.get('market_cap_display', '')
                pe_str = f" • P/E: {pe:.1f}" if pe else ""
                cap_str = f" • Cap: {cap}" if cap else ""
                canvas_lines.append(f"- **{ticker}** ({company}): ${price:,.2f} ({emoji} {change:+.2f}% today){pe_str}{cap_str}")
            canvas_lines.append("")
        
        # Alerts section
        alerts = report_data.get('alerts', {}).get('alerts', [])
        canvas_lines.append(f"## 🚨 Alerts ({len(alerts)})")
        if alerts:
            for a in alerts[:10]:
                canvas_lines.append(f"- {a.get('message', a.get('title', 'Alert'))}")
        else:
            canvas_lines.append("- ✅ No active alerts")
        canvas_lines.append("")
        
        # Reminders section
        reminders = report_data.get('reminders', {}).get('reminders', [])
        canvas_lines.append(f"## ⏰ Upcoming Reminders ({len(reminders)})")
        if reminders:
            for r in reminders[:10]:
                title = r.get('title', r.get('message', 'Reminder'))
                rel_time = r.get('relative_time', '')
                canvas_lines.append(f"- {title}" + (f" — *{rel_time}*" if rel_time else ""))
        else:
            canvas_lines.append("- ✅ No upcoming reminders")
        canvas_lines.append("")
        
        # System section
        if 'system' in report_data:
            s = report_data['system']
            canvas_lines.extend([
                "## 💻 System Health",
                f"- **CPU:** {s.get('cpu_percent', 0):.1f}%",
                f"- **Memory:** {s.get('memory_percent', 0):.1f}% ({s.get('memory_used_gb', 0):.1f} / {s.get('memory_total_gb', 0):.1f} GB)",
                f"- **Disk ({s.get('disk_mount', '/')}):** {s.get('disk_percent', 0):.1f}% ({s.get('disk_used_gb', 0):.1f} / {s.get('disk_total_gb', 0):.1f} GB)",
                f"- **Uptime:** {s.get('uptime', 'N/A')}",
                f"- **Network:** ↑{s.get('network_sent_gb', 0):.1f} GB / ↓{s.get('network_recv_gb', 0):.1f} GB",
                ""
            ])
        
        # Failures section
        if failures:
            canvas_lines.extend(["## ⚠️ Data Issues", *[f"- {f}" for f in failures], ""])
        
        # Footer
        canvas_lines.extend(["---", f"*Stash: `{stash_ref}`*" if stash_ref else ""])
        
        canvas_content = "\n".join(canvas_lines)
        
        # Save to canvas
        canvas_id = None
        if save_to_canvas:
            canvas_result = call_tool('canvas', {
                'action': 'create',
                'title': f"Daily Status/{now.strftime('%Y-%m-%d')} Recap",
                'content': canvas_content,
                'tags': ['status', 'recap', 'daily']
            })
            if canvas_result.get('ok'):
                canvas_id = canvas_result.get('data', {}).get('page_id')
        
        print(json.dumps({
            "ok": True,
            "speech": speech,
            "data": {
                "report": report_data,
                "stash_ref": stash_ref,
                "canvas_id": canvas_id,
                "image_ref": image_stash_ref,
                "failures": failures
            }
        }))
        
    except Exception as e:
        import traceback
        print(json.dumps({
            "ok": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "speech": f"Status recap failed: {e}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
