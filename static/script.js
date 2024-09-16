
function getRandomDarkColor() {
    const letters = '0123456789ABCDEF';
    let color = '#';
    for (let i = 0; i < 6; i++) {
        color += letters[Math.floor(Math.random() * 16)];
    }
    // Ensure the color is dark
    if (parseInt(color.substring(1, 3), 16) > 128) {
        color = color.substring(0, 1) + (parseInt(color.substring(1, 3), 16) - 128).toString(16).padStart(2, '0') + color.substring(3);
    }
    if (parseInt(color.substring(3, 5), 16) > 128) {
        color = color.substring(0, 3) + (parseInt(color.substring(3, 5), 16) - 128).toString(16).padStart(2, '0') + color.substring(5);
    }
    if (parseInt(color.substring(5, 7), 16) > 128) {
        color = color.substring(0, 5) + (parseInt(color.substring(5, 7), 16) - 128).toString(16).padStart(2, '0');
    }
    return color;
}

document.addEventListener('DOMContentLoaded', () => {
    const cardTitle = document.querySelector('.card h2');
    const cardDescription = document.querySelector('.card p');
    const randomDarkColor = getRandomDarkColor();
    if (cardTitle) {
        cardTitle.style.color = randomDarkColor;
    }
    if (cardDescription) {
        cardDescription.style.color = randomDarkColor;
    }
});