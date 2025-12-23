import random

# English adjectives
ADJECTIVES = [
    'happy', 'brave', 'clever', 'quick', 'strong', 'calm', 'wild', 'gentle',
    'bright', 'cool', 'swift', 'proud', 'alert', 'free', 'kind', 'bold',
    'fine', 'smart', 'young', 'nice', 'sweet', 'great', 'warm', 'soft',
    'active', 'eager', 'friendly', 'patient', 'cheerful', 'creative',
    'funny', 'curious', 'witty', 'sporty', 'noble', 'wonderful', 'keen',
    'lively', 'merry', 'jolly', 'dizzy', 'fuzzy', 'lucky'
]

# English animal names
ANIMALS = [
    'panda', 'tiger', 'eagle', 'fox', 'rabbit', 'wolf', 'bear', 'lion',
    'cat', 'dog', 'bird', 'fish', 'frog', 'hedgehog', 'mouse', 'owl',
    'beaver', 'badger', 'moose', 'falcon', 'goose', 'deer', 'otter', 'horse',
    'raven', 'swan', 'seal', 'sparrow', 'stork', 'whale', 'zebra',
    'dolphin', 'hamster', 'koala', 'salmon', 'penguin', 'raccoon', 'turtle'
]

CONSONANTS = 'bcdfghjklmnprstvw'
VOWELS = 'aeiou'


def generate_username(existing_usernames=None):
    """Generate a unique username like 'happypanda'."""
    if existing_usernames is None:
        existing_usernames = set()

    attempts = 0
    while attempts < 1000:
        adj = random.choice(ADJECTIVES)
        animal = random.choice(ANIMALS)
        username = f"{adj}{animal}"
        if username not in existing_usernames:
            return username
        attempts += 1

    # Fallback: add number
    return f"{adj}{animal}{random.randint(1, 999)}"


def generate_password():
    """Generate password in cvcvcvnn format (e.g., 'bacado42')."""
    password = ''
    password += random.choice(CONSONANTS)
    password += random.choice(VOWELS)
    password += random.choice(CONSONANTS)
    password += random.choice(VOWELS)
    password += random.choice(CONSONANTS)
    password += random.choice(VOWELS)
    password += str(random.randint(0, 9))
    password += str(random.randint(0, 9))
    return password


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in {'pdf', 'png', 'jpg', 'jpeg', 'gif'}
