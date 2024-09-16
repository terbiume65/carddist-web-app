from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import random

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Sample card pool
card_pool = [
    {"title": "Werewolf", "description": "You are a Werewolf."},
    {"title": "Seer", "description": "You can see other players' roles."},
    {"title": "Villager", "description": "You are a Villager."},
]

users = {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/join', methods=['POST'])
def join():
    username = request.form['username']
    # Check if user is already in the game
    if username not in users:
        users[username] = None  # Initialize user without a card
    session['username'] = username
    return redirect(url_for('user'))

@app.route('/user')
def user():
    username = session.get('username')
    card = users.get(username)
    return render_template('user.html', card=card)

@app.route('/admin')
def admin():
    return render_template('admin.html', users=users, card_pool=card_pool)

@app.route('/add_card', methods=['POST'])
def add_card():
    title = request.form['title']
    description = request.form['description']
    card_pool.append({"title": title, "description": description})
    return redirect(url_for('admin'))

@app.route('/distribute_cards')
def distribute_cards():
    available_users = [user for user in users if users[user] is None]
    random.shuffle(card_pool)
    for user in available_users:
        if card_pool:
            users[user] = card_pool.pop()
    return redirect(url_for('admin'))

@app.route('/get_card')
def get_card():
    username = session.get('username')
    return jsonify(users.get(username))

@app.route('/delete_card', methods=['POST'])
def delete_card():
    title = request.form['title']
    global card_pool
    card_pool = [card for card in card_pool if card['title'] != title]
    return redirect(url_for('admin'))

if __name__ == '__main__':
    app.run(debug=True)