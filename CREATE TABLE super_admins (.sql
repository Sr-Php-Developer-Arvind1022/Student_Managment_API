CREATE TABLE super_admins (
    id SERIAL PRIMARY KEY, -- Auto-incrementing ID
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL, -- Store hashed password, not plain text
    role VARCHAR(50) DEFAULT 'super_admin',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE admins (
    admins_id_pk INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(50) DEFAULT 'admin',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);
CREATE TABLE login_table (
    login_table_id_pk INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(150) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    status ENUM('active', 'inactive', 'suspended') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (login_id) REFERENCES admins(admins_id_pk),
    INDEX (email),
    INDEX (status)
);
#student table
CREATE TABLE student_table (
    student_table_id_pk INT AUTO_INCREMENT PRIMARY KEY,
    login_id_fk INT NOT NULL,
    enrollment_number VARCHAR(50) UNIQUE NOT NULL,
    status ENUM('active', 'inactive', 'passed', 'dropout') DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (student_table_id_pk) REFERENCES login_table(login_table_id_pk),
    INDEX (enrollment_number),
    INDEX (status)
);

CREATE TABLE student_basic_info (
    student_basic_info_id_pk INT AUTO_INCREMENT PRIMARY KEY,
    student_id_fk INT NOT NULL,
    first_name VARCHAR(100) NOT NULL,
    middle_name VARCHAR(100) DEFAULT NULL,
    last_name VARCHAR(100) DEFAULT NULL,
    dob DATE NOT NULL,
    gender ENUM('male', 'female', 'other') DEFAULT NULL,
    contact_number VARCHAR(15) DEFAULT NULL,
    blood_group VARCHAR(10) DEFAULT NULL,
    nationality VARCHAR(100) DEFAULT NULL,
    FOREIGN KEY (student_basic_info_id_pk) REFERENCES student_table(student_table_id_pk),
    INDEX (first_name),
    INDEX (dob)
);

CREATE TABLE student_address (
    student_address_id_pk INT AUTO_INCREMENT PRIMARY KEY,
    student_id_fk INT NOT NULL,
    address_line1 VARCHAR(255) DEFAULT NULL,
    address_line2 VARCHAR(255) DEFAULT NULL,
    city VARCHAR(100) DEFAULT NULL,
    state VARCHAR(100) DEFAULT NULL,
    postal_code VARCHAR(20) DEFAULT NULL,
    country VARCHAR(100) DEFAULT NULL,
    FOREIGN KEY (student_address_id_pk) REFERENCES student_table(student_table_id_pk),
    INDEX (city),
    INDEX (state)
);
CREATE TABLE student_parents (
    student_parents_id_pk INT AUTO_INCREMENT PRIMARY KEY,
    student_id_fk INT NOT NULL,
    father_name VARCHAR(100) DEFAULT NULL,
    mother_name VARCHAR(100) DEFAULT NULL,
    guardian_name VARCHAR(100) DEFAULT NULL,
    contact_number VARCHAR(15) DEFAULT NULL,
    email VARCHAR(150) DEFAULT NULL,
    occupation VARCHAR(100) DEFAULT NULL,
    FOREIGN KEY (student_parents_id_pk) REFERENCES student_table(student_table_id_pk),
    INDEX (father_name),
    INDEX (mother_name)
);
CREATE TABLE student_education (
    student_education_id_pk INT AUTO_INCREMENT PRIMARY KEY,
    student_id_fk INT NOT NULL,
    school_name VARCHAR(200) DEFAULT NULL,
    board VARCHAR(100) DEFAULT NULL,
    passing_year YEAR DEFAULT NULL,
    percentage DECIMAL(5,2) DEFAULT NULL,
    stream VARCHAR(50) DEFAULT NULL,
    FOREIGN KEY (student_education_id_pk) REFERENCES student_table(student_table_id_pk),
    INDEX (school_name),
    INDEX (passing_year)
);
